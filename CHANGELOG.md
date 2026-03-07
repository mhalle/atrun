# Changelog

## 0.9.0

- Add `info --social` flag: shows publisher profile (followers, bio) and Bluesky post engagement (likes, reposts, replies)
- Social info available in both human-readable and `--json` output

## 0.8.0

- Automatic `derivedFrom` linking: new records point back to the previous version of the same package with a cryptographically verified strongRef (uri + CID)
- Show `derivedFrom` in `info` output
- Include project URL in Bluesky post link card description

## 0.7.1

- Include description and URL in Bluesky post text (clipped to 300 graphemes)
- Add link facet on URL in post text so it's clickable

## 0.7.0

- Remove Deno ecosystem support (doesn't fit single-artifact distribution model)
- Remove `denoEcosystem` from lexicon
- Remove `--permission` flag from publish
- Add `--engine` flag to install and run for choosing Node.js package manager (pnpm, bun, npm)
- Add `--dist` flag to info command for printing distribution artifact URL
- Add `gh:owner/repo` and `npm:package` dist URL shorthands for publish
- Add `--info` display of ecosystem type in info output
- Detect and report misconfigured pnpm global bin directory with setup instructions
- Display package name, version, and ecosystem when installing
- Node verified install uses pnpm for verification, chosen engine for global install

## 0.6.0

- Add `version`, `description`, `license`, and `url` metadata fields to lexicon
- Extract metadata from dist artifacts at publish time (wheel METADATA, npm package.json)
- Support `License-Expression` field (PEP 639) in wheel metadata
- Local dist file metadata extraction (no network fetch needed when `--dist-file` is provided)
- Hash verification between local `--dist-file` and remote `--dist-url` when both are given
- Lockfile is optional when publishing with `--dist-url` and no `--deps`
- Add `--post` flag to publish: creates a Bluesky post with a link card embedding the record
- Accept Bluesky post URLs (`https://bsky.app/profile/.../post/...`) in all commands
- Accept XRPC HTTPS URLs in all commands (alongside AT URIs)
- Add `--unsigned` flag for plain HTTPS URLs without AT Protocol verification
- `info` command shows AT Protocol envelope (publisher, CID, timestamp) alongside content
- `info --json` returns structured output with separate `at` and `content` sections
- Remove `cat` command (superseded by `info --json`)
- Three-state install: auto (default), `--deps` (force verification), `--no-deps` (skip verification)
- Full docstrings and help text for all commands, options, and modules

## 0.5.0

- Add Node.js (npm) ecosystem support
- New `ecosystems` subpackage with registry, detection, and per-ecosystem modules
- Parse package-lock.json (Node) lockfiles
- Auto-detect ecosystem from lockfile content or dist URL
- Add `dependencies` array to `depEntry` for dependency graph storage
- Add `--ecosystem` option to publish (python/node, auto-detected if omitted)
- Add `--deps`/`--no-deps` flags to publish and install
- Publish with `--no-deps --dist-url` requires no lockfile
- Verified installs via frozen lockfiles (pnpm for Node)
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
