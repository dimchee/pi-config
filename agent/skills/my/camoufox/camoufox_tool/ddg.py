"""Pure DuckDuckGo Lite logic: tokens, URL unwrapping, markdown, extraction JS."""

import base64
import json
import re
import urllib.parse

DDG_LITE = "https://lite.duckduckgo.com/lite/"
DDG_HTML = "https://html.duckduckgo.com/html/"  # fallback engine (ticket P1#4)
ENGINES = {"lite": DDG_LITE, "html": DDG_HTML}

# Extracts organic results + the "Next Page" form fields from the lite DOM.
EXTRACT_JS = """
() => {
  const out = [];
  for (const a of document.querySelectorAll('a.result-link')) {
    const row = a.closest('tr');
    let snippet = '';
    let domain = '';
    let el = row ? row.nextElementSibling : null;
    for (let i = 0; i < 4 && el; i++) {
      const sn = el.querySelector('td.result-snippet');
      const lt = el.querySelector('span.link-text');
      if (!sn && !lt) break;
      if (sn && !snippet) snippet = sn.textContent.trim();
      if (lt && !domain) domain = lt.textContent.trim();
      el = el.nextElementSibling;
    }
    out.push({
      title: a.textContent.trim(),
      href: a.getAttribute('href') || '',
      domain,
      snippet,
    });
  }
  const nf = document.querySelector('form.next_form');
  let nextForm = null;
  if (nf) {
    nextForm = {};
    for (const input of nf.querySelectorAll('input[type="hidden"]')) {
      nextForm[input.name] = input.value;
    }
  }
  return { results: out, nextForm };
}
"""


def encode_token(engine: str, next_form: dict) -> str | None:
    """Opaque base64url blob of the engine name + next-page form fields.

    The engine is baked into the token so `--next` keeps working across the
    fallback engine without a separate flag.
    """
    if not next_form:
        return None
    raw = json.dumps({"e": engine, "f": next_form}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_token(token: str) -> tuple[str, dict]:
    """Returns (engine, next_form); legacy pre-engine tokens decode as lite."""
    pad = "=" * (-len(token) % 4)
    # MUST be urlsafe: tokens are produced with urlsafe_b64encode; standard
    # b64decode would silently drop '-'/'_' chars and corrupt the payload.
    raw = json.loads(base64.urlsafe_b64decode(token + pad))
    if isinstance(raw, dict) and "f" in raw and "e" in raw:
        return raw["e"], raw["f"]
    return "lite", raw  # legacy token format


# Same contract as EXTRACT_JS but for the html.duckduckgo.com layout:
# results live in div.result blocks, pagination in a form with input[name=s].
HTML_EXTRACT_JS = """
() => {
  const out = [];
  for (const a of document.querySelectorAll('a.result__a')) {
    const box = a.closest('.result');
    out.push({
      title: a.textContent.trim(),
      href: a.getAttribute('href') || '',
      domain: '',
      snippet: box ? ((box.querySelector('.result__snippet') || {}).textContent || '').trim() : '',
    });
  }
  const nf = document.querySelector('input[name="s"]')?.closest('form');
  let nextForm = null;
  if (nf) {
    nextForm = {};
    for (const input of nf.querySelectorAll('input[type="hidden"]')) {
      nextForm[input.name] = input.value;
    }
    if (!('s' in nextForm)) return { results: out, nextForm: null };
    const q = nf.querySelector('input[name="q"]');
    if (q) nextForm.q = q.value;
    const s = nf.querySelector('input[name="s"]');
    if (s) nextForm.s = s.value;
  }
  return { results: out, nextForm };
}
"""


def extract_js_for(engine: str) -> str:
    return HTML_EXTRACT_JS if engine == "html" else EXTRACT_JS


def resolve_url(href: str) -> str | None:
    """Resolve a result link to its real target URL."""
    if not href:
        return None
    if href.startswith("//duckduckgo.com/l/"):
        href = "https:" + href  # html-engine wraps links schemeless
    url = urllib.parse.urljoin(DDG_LITE, href)
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)

    # Organic results are wrapped in a /l/?uddg=<encoded target> redirect.
    if "uddg" in qs:
        return qs["uddg"][0]
    return url


def filter_results(items: list[dict]) -> list[dict]:
    """Keep only resolvable, titled results; unwrap redirect links."""
    out = []
    for item in items:
        url = resolve_url(item.get("href", ""))
        if not url or not item.get("title", "").strip():
            continue  # skip: unresolvable links, blank titles
        out.append(
            {
                "title": item["title"],
                "url": url,
                "domain": item.get("domain", ""),
                "snippet": item.get("snippet", ""),
            }
        )
    return out


# Control chars and every character str.splitlines() treats as a line break
# (\x1c-\x1e, \x85, \u2028, \u2029): any of these would corrupt line-based
# markdown parsing by agents.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]")


def _clean(s: str) -> str:
    return _CONTROL_RE.sub("", s)


def build_markdown(query: str | None, results: list, token: str | None) -> str:
    query = _clean(query or "")
    lines = [f'# DuckDuckGo results for "{query}"', ""]
    if not results:
        lines.append("_No results found._")
    else:
        for i, r in enumerate(results, 1):
            title = _clean(r["title"])
            snippet = _clean(r["snippet"])
            lines.append(f"{i}. [{title}]({r['url']})")
            if snippet.strip():
                lines.append(f"   {snippet}")
            lines.append("")
    lines.append("---")
    if token:
        lines.append(f"More results: cam.py search --next {token}")
    else:
        lines.append("_No more results._")
    return "\n".join(lines)
