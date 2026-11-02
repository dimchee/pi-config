---
name: python-scratch
description: Run quick Python scripts using Nix-provided packages. Use for one-off automation, data extraction, API calls, file transformations, data processing, experiments, and temporary utilities.
---

# Python Scratch Scripts

## Purpose

Use Python as a fast automation tool.

This skill is for:
- quick scripts
- temporary data processing
- API calls
- file manipulation
- format conversion
- small experiments
- system automation

Do not turn small tasks into full Python projects unless explicitly requested!

## Core Rules

- Prefer the Python standard library when possible.
- Use Nix to provide external Python packages.
- Do not install packages globally.
- Do not modify the user's Python environment.
- Keep scripts small and disposable.

## Script Workflow

Before writing code:

1. Decide if Python is the right tool.
2. Check whether the standard library is enough.
3. If dependencies are needed, find matching Nix packages.
4. Create the smallest script that solves the task.
5. Run it and verify the output.

## Running Simple Scripts

For standard-library scripts:

```bash
python3 script.py
````

For scripts requiring packages, use legacy `nix-shell -p` (NOT `nix shell nixpkgs#python3Packages.X`):

```bash
nix-shell -p python3Packages.openpyxl --run 'python3 script.py'
```

Multiple packages:

```bash
nix-shell -p python3Packages.openpyxl python3Packages.pandas --run 'python3 script.py'
```

> Why not `nix shell nixpkgs#python3Packages.X -c python3 ...`?
> It does not work in this environment. Python packages in nixpkgs are separate store
> paths and are NOT merged into the base python's site-packages, so `import X` fails.
> Additionally, `nix shell` for a package without `bin/` entries adds nothing to PATH,
> so `python3` resolves to the user-profile python (`~/.nix-profile/bin/python3`), which
> has none of the package. `nix-shell -p` sets PYTHONPATH automatically.
>
> `nix shell 'nixpkgs#python3.withPackages(ps: [ps.X])'` also fails here (parser treats
> `nixpkgs` as a local path). Manual fallback if `nix-shell` is unavailable:
>
> ```bash
> PYTHONPATH="$(nix build --no-link --print-out-paths nixpkgs#python3Packages.X)/lib/python3.13/site-packages" \
>   python3 script.py
> ```
> (include transitive deps such as `et_xmlfile` for openpyxl in PYTHONPATH too).

## Common Package Mapping

Use Nix packages for common needs:

| Task                | Package        |
| ------------------- | -------------- |
| HTTP requests       | requests       |
| JSON APIs           | requests       |
| Data tables         | pandas         |
| Excel files         | openpyxl       |
| Images              | pillow         |
| HTML parsing        | beautifulsoup4 |
| YAML files          | pyyaml         |
| Terminal formatting | rich           |

## Script Style

Prefer:

* one file
* clear inputs and outputs
* command-line arguments when useful
* readable error messages
* no unnecessary frameworks

Example:

```python
from pathlib import Path

for file in Path(".").glob("*.txt"):
    print(file)
```

## Data Safety

Before modifying files:

* inspect input files first
* avoid destructive operations
* create backups when changing user data
* confirm before deleting or overwriting important files
* all intermediate files should be in `tmp/`

## When Not To Use

Do not use this skill for:

* production applications
* libraries intended for publishing
* large repositories
* long-running services
* complex Python environments

Use a dedicated development workflow instead.
