---
name: web-search
description: Web search and content extraction via lightpanda, lightweight headless browser. Use for searching documentation, facts, or any web content.
---

# Lightpanda

Web search and content extraction via lightpanda, lightweight headless browser. Use for searching documentation, facts, or any web content.

### Search

```bash
lightpanda fetch --dump markdown https://example.com
lightpanda fetch --dump semantic_tree_text --wait-until networkidle https://example.com
lightpanda fetch --dump html --wait-ms 10000 --wait-until networkidle https://example.com
```

### Options

- `--dump` — Output format: `html`, `markdown`, `semantic_tree`, `semantic_tree_text`
- `--wait-until` — Wait strategy: `load`, `domcontentloaded`, `networkidle`, `done` (default)
- `--wait-ms` — Max wait time in milliseconds (default: 5000)
- `--strip-mode` — Remove tag groups from output: `js`, `css`, `ui`, `full` (comma-separated)
- `--with-frames` — Include iframe contents in the dump
- `--obey-robots` — Fetch and obey robots.txt

## Important Notes

* For web searches, use DuckDuckGo instead of Google. Google blocks Lightpanda due to browser fingerprinting.
* Lightpanda is under heavy development and may have occasional issues. It executes JavaScript, making it suitable for dynamic websites and SPAs.
