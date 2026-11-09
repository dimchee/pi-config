---
name: lean4
description: Lean 4 theorem proving skill. Use when editing .lean files, debugging Lean 4 builds (type mismatch, sorry, failed to synthesize instance, axiom warnings, lake build errors), searching mathlib for lemmas, formalizing mathematics in Lean, finding counterexamples, or learning Lean 4 concepts. Do NOT trigger for Coq/Rocq, Agda, Isabelle, HOL4, Mizar, Idris, or other non-Lean theorem provers.
---

# Lean 4 Theorem Proving

Use this skill when editing Lean 4 proofs, debugging Lean builds, formalizing mathematics in Lean, or learning Lean 4 concepts.

## Core Principles

**Search before prove.** Many mathematical facts already exist in mathlib. Search exhaustively before writing tactics.

**Build incrementally.** Lean's type checker is your test suite — if it compiles with no sorries and standard axioms only, the proof is sound.

**Respect scope.** Follow the user's preference: fill one sorry, its transitive dependencies, all sorries in a file, or everything. Ask if unclear.

**Use 100-character line width for Lean files.** Do not wrap lines at 80 characters — Lean and mathlib convention is 100. See [mathlib-style](references/mathlib-style.md) for breaking strategies when lines exceed 100.

**Mathlib style.** For ordinary mathematical lambdas, write `fun x ↦ ...` (`\mapsto`), not `fun x => ...`. Use `=>` for `match`/`do` branches and metaprogramming. Prefer `show P by tac` for tactic proofs; use `show P from term` for term proofs. See [mathlib-style](references/mathlib-style.md).

**Preserve statements, signatures, and docstrings** — they're the file's API. Don't change theorem/lemma statements, type signatures, or docstrings unless the user explicitly requests it. If a proof seems to require changing a statement or adding a custom axiom, stop and discuss with the user first.

## Prerequisites

- **Lean 4** — `lean --version`
- **Lake** — `lake --version`
- **Python 3** — `python3 --version` (for helper scripts)
- **ripgrep** (optional, 10-100x faster search)

## Typical Workflow

```
1. Draft / Formalize  →  Write Lean declarations
2. Prove              →  Fill sorries
3. Refactor           →  Simplify proof strategies
4. Golf               →  Optimize proofs
5. Checkpoint         →  Save progress
```

**Proving loop:** For each sorry, search mathlib → generate tactic candidates → test via `lean_multi_attempt` or `lake env lean` → validate → next sorry. Use `lake build` at the end for project-wide verification.

## Scripts

Helper scripts are in `scripts/`. Run them from the skill directory (where SKILL.md lives) or use relative paths:

```bash
# All scripts are at skills/lean4/scripts/
python3 scripts/sorry_analyzer.py . --format=summary
bash scripts/check_axioms_inline.sh src/File.lean
bash scripts/search_mathlib.sh "continuous.*compact" name
bash scripts/smart_search.sh "Cauchy Schwarz" --source=all
python3 scripts/find_golfable.py MyFile.lean --filter-false-positives
bash scripts/find_usages.sh theorem_name
python3 scripts/minimize_imports.py MyFile.lean
python3 scripts/parse_lean_errors.py error_output.txt
bash scripts/unused_declarations.sh src/
```

| Script | Purpose | Usage |
|--------|---------|-------|
| `sorry_analyzer.py` | Extract and report sorries with context | `python3 scripts/sorry_analyzer.py <file-or-dir> [--format=text\|json\|markdown\|summary] [--report-only]` |
| `check_axioms_inline.sh` | Best-effort axiom scan (top-level decls) | `bash scripts/check_axioms_inline.sh <file-or-dir> [--report-only]` |
| `search_mathlib.sh` | Find lemmas in mathlib via grep | `bash scripts/search_mathlib.sh <query> [name\|type\|content]` |
| `smart_search.sh` | Multi-source search (LeanSearch, Loogle, mathlib) | `bash scripts/smart_search.sh <query> [--source=leansearch\|loogle\|mathlib\|all]` |
| `find_golfable.py` | Detect proof optimization patterns | `python3 scripts/find_golfable.py <file> [--filter-false-positives]` |
| `find_usages.sh` | Find all uses of a declaration | `bash scripts/find_usages.sh <decl-name> [<dir>]` |
| `minimize_imports.py` | Remove unused imports | `python3 scripts/minimize_imports.py <file> [--dry-run]` |
| `parse_lean_errors.py` | Parse Lean errors into structured JSON | `python3 scripts/parse_lean_errors.py <error-file>` |
| `unused_declarations.sh` | Find unused theorems/defs | `bash scripts/unused_declarations.sh <dir> [--report-only]` |

**Exit codes:** `sorry_analyzer.py`, `check_axioms_inline.sh`, and `unused_declarations.sh` exit 1 on findings (useful for CI gating). Use `--report-only` to exit 0 on findings while still reporting errors.

## Automation Tactics

Try in order (stop on first success):
`rfl` → `simp` → `ring` → `linarith` → `nlinarith` → `omega` → `exact?` → `apply?` → `grind` → `aesop`

`exact?`/`apply?` query mathlib (slow). `grind` and `aesop` are powerful but may timeout. See [grind-tactic](references/grind-tactic.md) for interactive workflows.

## Quality Gate

A proof is complete when:
- `lake build` passes
- Zero sorries in scope
- Only standard axioms (`propext`, `Classical.choice`, `Quot.sound`)
- No statement changes without permission

Verification: `lake env lean <path/to/File.lean>` (from project root) per-file → `lake build` project-wide.

## Common Fixes

See [compilation-errors](references/compilation-errors.md) for error-by-error guidance (type mismatch, unknown identifier, failed to synthesize instance, timeout, etc.).

## Type Class Patterns

```lean
-- Local instance for this proof block
haveI : MeasurableSpace Ω := inferInstance
letI : Fintype α := ⟨...⟩

-- Scoped instances (affects current section)
open scoped Topology MeasureTheory
```

`omit [Inst] in` removes an unused section instance from the following declaration.
Place it **before** the declaration docstring.

```lean
variable {α : Type*} [MeasurableSpace α]

omit [MeasurableSpace α] in
/-- doc -/
theorem foo : True := trivial
```

See [domain-patterns](references/domain-patterns.md#pattern-7-managing-section-variables-with-omit) for more.

## Cold Start / Fresh Worktree

- After `lake clean`, prime the cache: `lake cache get` or `lake exe cache get`
- If Lean LSP is cold or timing out, run `lake build` first to bootstrap
- Do **not** symlink another worktree's `.lake/build`; use Lake cache instead

## References

**Cycle Engine:** [cycle-engine](references/cycle-engine.md) — proof engine mechanics (stuck detection, deep mode, falsification)

**LSP Tools:** [lean-lsp-server](references/lean-lsp-server.md) (quick start), [lean-lsp-tools-api](references/lean-lsp-tools-api.md) (full API)

**Search:** [mathlib-guide](references/mathlib-guide.md) (read when searching for lemmas), [lean-phrasebook](references/lean-phrasebook.md) (math→Lean translations)

**Errors:** [compilation-errors](references/compilation-errors.md) (read first for any build error), [instance-pollution](references/instance-pollution.md) (typeclass conflicts), [compiler-guided-repair](references/compiler-guided-repair.md) (repair strategies)

**Tactics:** [tactics-reference](references/tactics-reference.md) (tactic lookup), [grind-tactic](references/grind-tactic.md) (SMT-style automation), [simp-reference](references/simp-reference.md) (simp hygiene), [tactic-patterns](references/tactic-patterns.md), [calc-patterns](references/calc-patterns.md)

**Proof Development:** [proof-templates](references/proof-templates.md), [proof-refactoring](references/proof-refactoring.md), [proof-simplification](references/proof-simplification.md), [sorry-filling](references/sorry-filling.md)

**Optimization:** [proof-golfing](references/proof-golfing.md), [proof-golfing-patterns](references/proof-golfing-patterns.md), [performance-optimization](references/performance-optimization.md), [profiling-workflows](references/profiling-workflows.md)

**Domain:** [domain-patterns](references/domain-patterns.md) (grep `## Area`), [measure-theory](references/measure-theory.md), [axiom-elimination](references/axiom-elimination.md)

**Style:** [mathlib-style](references/mathlib-style.md), [verso-docs](references/verso-docs.md) (Verso doc comment roles)

**Custom Syntax:** [lean4-custom-syntax](references/lean4-custom-syntax.md), [metaprogramming-patterns](references/metaprogramming-patterns.md), [scaffold-dsl](references/scaffold-dsl.md), [json-patterns](references/json-patterns.md)

**Quality:** [linter-authoring](references/linter-authoring.md), [ffi-interop](references/ffi-interop.md)

**Workflows:** [agent-workflows](references/agent-workflows.md), [subagent-workflows](references/subagent-workflows.md), [learn-pathways](references/learn-pathways.md) (intent taxonomy, source handling)

**Disprove:** [disprove-engine](references/disprove-engine.md) — counterexample search mechanics

**Internals:** [review-hook-schema](references/review-hook-schema.md), [compiler-internals](references/compiler-internals.md)
