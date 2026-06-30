# APPEND_SYSTEM.md

## Workspace & Temporary Files

The project workspace is the default location for all work.

**Never use system temporary directories** (e.g. `/tmp`, `/var/tmp`, `$TMPDIR`, `mktemp`, or language/platform temp APIs) unless the user explicitly requests them or a tool strictly requires them.

Use **`./tmp`** for all temporary files, including:

* downloads
* archives
* extracted files
* caches
* logs
* build artifacts
* intermediate outputs
* scratch files

Before creating any temporary files, ensure it exists:

```sh
mkdir -p ./tmp
```

When writing shell commands or code, always prefer paths under `./tmp` over system temp directories.

If a dependency requires a system temp directory, explain why before using it. Otherwise, treat the use of `./tmp` as mandatory.
