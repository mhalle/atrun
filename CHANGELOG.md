# Changelog

## 0.5.0

- Add Node.js (npm) and Deno ecosystem support
- New `ecosystems` subpackage with registry, detection, and per-ecosystem modules
- Parse package-lock.json (Node) and deno.lock v4/v5 (Deno) lockfiles
- Auto-detect ecosystem from lockfile content or dist URL
- Add `denoEcosystem` to lexicon with `runtime` and `permissions` fields
- Add `dependencies` array to `depEntry` for dependency graph storage
- Add `version`, `description`, `license`, and `url` metadata fields to record
- Extract metadata from dist artifacts at publish time (wheel, npm tarball, JSR)
- Add `--ecosystem` option to publish (python/node/deno, auto-detected if omitted)
- Add `--permission` option to publish for Deno permissions
- Add `--deps`/`--no-deps` flags to publish and install
- Publish with `--no-deps --dist-url` requires no lockfile
- Verified installs via frozen lockfiles (pnpm for Node, deno --frozen for Deno)
- Install auto-uses frozen lockfile verification when record has dependency graph
- `info` shows record metadata by default; `--registry` fetches from ecosystem registry
- Strip leading `@` and whitespace from handle on login
- Add `pyyaml` dependency (for pnpm lockfile reconstruction)

## 0.4.0

- Switch from parsing `uv.lock` (private format) to `pylock.toml` via `uv export` (PEP 751)
- Add `ecosystem` discriminated union to record format (python, node)
- Add `source` field (strongRef) on dependency entries for upstream record linking
- Add `derivedFrom` field (strongRef) for record provenance
- Add `cat` command to print full record JSON from an AT URI
- Add `resolve` command to output requirements.txt to stdout
- Add `install` command with passthrough to `uv tool install`
- Add `info` command to show package metadata from wheel
- Add `--lockfile` flag to publish (file path, `-` for stdin, or auto via `uv export`)
- Add `--dist-url` to publish (downloads and hashes remotely, no local file needed)
- Rename `--wheel`/`--wheel-url` to `--dist-file`/`--dist-url`
- Drop `pythonVersion` and `platform` top-level fields in favor of `ecosystem` object
- Rename `hint` field to `source`, change type from at-uri to strongRef
- Add Apache-2.0 license and project URLs to pyproject.toml

## 0.3.0

- Add `cat` command to fetch and print full record JSON
- Add `resolve` command to output requirements.txt to stdout
- Add `install` command wrapping `uv tool install` with passthrough args
- Add `install --dry-run` to print the uv command without running it

## 0.2.0

- Add `package` field to record identifying the root package
- Add `--wheel` and `--wheel-url` flags to include project wheel in record
- Add `--dry-run` flag to preview record without publishing
- Better error message on login failure (401)
- Fix requirements.txt format for `uv pip install`

## 0.1.0

- Initial implementation
- `login` command for Bluesky authentication
- `publish` command to publish `uv.lock` as AT Protocol record
- `run` command to fetch and execute from an AT URI
- `dev.atrun.module` lexicon definition
