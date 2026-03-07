# atrun

Social package distribution on AT Protocol.

## Why

Package registries like PyPI, npm, and crates.io are centralized services that store both metadata and artifacts. They work well, but they're single points of control — for metadata, for identity, and for discovery.

atrun takes a different approach: it uses [AT Protocol](https://atproto.com/) (the protocol behind [Bluesky](https://bsky.app)) as a decentralized package registry. Package records live in users' personal data repositories, the same infrastructure that stores their social posts.

A `dev.atrun.module` record is a **signed manifest** — it doesn't contain code, it points to artifacts hosted elsewhere (GitHub Releases, PyPI, npm, crates.io) and adds:

- **Identity** — every record is tied to a DID (decentralized identifier), so you know who published it
- **Integrity** — every record has a CID (content hash) and dependency hashes for tamper detection
- **Provenance** — `derivedFrom` creates verifiable version chains, each locked by CID
- **Portability** — records aren't locked to one server; users can move between PDS instances
- **Social distribution** — records can be embedded in Bluesky posts, making package announcements native to the social network

The record is ecosystem-agnostic. The same format works for Python wheels, npm tarballs, and Rust crates. The installer picks the right tool (uv, pnpm, cargo) based on the ecosystem field.

### Architecture

AT Protocol has a layered architecture that maps naturally to package distribution:

- **PDS** (Personal Data Server) — stores your records. This is where atrun publishes today.
- **AppView** — aggregates and indexes records across all users. A future AppView for `dev.atrun.module` could provide search, discovery, dependency graphs, trust analysis, and supply chain monitoring across the entire network.

Anyone can publish. AppViews decide how to present it. Multiple competing AppViews could coexist — one focused on security auditing, another on discovery, another on enterprise compliance.

## Install

```
uv tool install atrun
```

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (for Python ecosystem)
- [pnpm](https://pnpm.io/), [bun](https://bun.sh/), or [npm](https://www.npmjs.com/) (for Node.js ecosystem)
- [cargo](https://doc.rust-lang.org/cargo/) (for Rust ecosystem)

Only the tools for ecosystems you use are required.

## Quick start

### Authenticate

Create an [app password](https://bsky.app/settings/app-passwords) on Bluesky, then:

```
atrun login --handle alice.bsky.social
```

### Publish a package

From a Python project with a wheel:

```
atrun publish --dist-file dist/mypackage-1.0.0-py3-none-any.whl \
              --dist-url https://github.com/me/mypackage/releases/download/v1.0.0/mypackage-1.0.0-py3-none-any.whl
```

From an npm tarball (auto-detected):

```
atrun publish --dist-url https://registry.npmjs.org/cowsay/-/cowsay-1.6.0.tgz
```

Using shorthands:

```
atrun publish --dist-url gh:me/mypackage           # latest GitHub release
atrun publish --dist-url gh:me/mypackage@v1.0.0    # specific release
atrun publish --dist-url npm:cowsay                 # latest npm version
atrun publish --dist-url npm:cowsay@1.6.0           # specific version
atrun publish --dist-url crate:ripgrep              # latest crate
atrun publish --dist-url crate:ripgrep@14.1.1       # specific version
```

With a Bluesky post:

```
atrun publish --dist-url npm:cowsay --post
```

Preview without publishing:

```
atrun publish --dist-url crate:ripgrep --dry-run
```

### Include the dependency graph

By default, only the main package is included. To enable frozen lockfile verification on install, include the full dependency graph:

```
atrun publish --lockfile Cargo.lock --dist-url crate:ripgrep --deps
```

The lockfile can be omitted for auto-export (Python only, via `uv export`):

```
atrun publish --dist-file dist/mypackage-1.0.0-py3-none-any.whl \
              --dist-url https://example.com/mypackage-1.0.0-py3-none-any.whl \
              --deps
```

### Install a package

```
atrun install at://did:plc:abc123/dev.atrun.module/3mgxyz
```

All URL formats work:

```
atrun install at://did:plc:abc123/dev.atrun.module/3mgxyz
atrun install 'https://bsky.social/xrpc/com.atproto.repo.getRecord?repo=did:plc:abc123&collection=dev.atrun.module&rkey=3mgxyz'
atrun install https://bsky.app/profile/alice.bsky.social/post/3mgxyz
```

Choose a Node.js package manager:

```
atrun install --engine bun at://did:plc:abc123/dev.atrun.module/3mgxyz
atrun install --engine npm at://did:plc:abc123/dev.atrun.module/3mgxyz
```

Control dependency verification:

```
atrun install --deps at://...      # require frozen lockfile verification
atrun install --no-deps at://...   # skip verification, let the package manager resolve
```

### Inspect a record

```
atrun info at://did:plc:abc123/dev.atrun.module/3mgxyz
```

```
package: ripgrep
version: 15.1.0
ecosystem: rust
description: ripgrep is a line-oriented search tool...
license: Unlicense OR MIT
url: https://github.com/BurntSushi/ripgrep
hash: sha256:f388c4955f85477c28a8667355819844a06614b083c23517f0e86bd1d6d82b73
dependencies: 1

publisher: alice.bsky.social (did:plc:abc123)
timestamp: 2026-03-07T05:02:29.773027Z
cid: bafyreihddco5gubbss4vmhe4464zb47kt4p4lzmp5acy766o3alxvrjoam
```

Structured JSON:

```
atrun info --json at://did:plc:abc123/dev.atrun.module/3mgxyz
```

Full raw record from the PDS:

```
atrun info --raw at://did:plc:abc123/dev.atrun.module/3mgxyz
```

Social context (publisher profile, post engagement):

```
atrun info --social at://did:plc:abc123/dev.atrun.module/3mgxyz
```

Get the distribution URL for use with other tools:

```
uv add $(atrun info --dist at://did:plc:abc123/dev.atrun.module/3mgxyz)
pnpm install $(atrun info --dist at://did:plc:abc123/dev.atrun.module/3mgxyz)
```

Registry metadata (from PyPI, npm, or crates.io):

```
atrun info --registry at://did:plc:abc123/dev.atrun.module/3mgxyz
```

### Resolve dependencies

Print dependencies in the ecosystem's native format:

```
atrun resolve at://did:plc:abc123/dev.atrun.module/3mgxyz
```

### Run a package

Install into a temporary environment and execute:

```
atrun run at://did:plc:abc123/dev.atrun.module/3mgxyz
```

## Version chains

When you publish a new version of a package, atrun automatically links it to the previous version via `derivedFrom` — a cryptographically verified back-reference (AT URI + CID). This creates a tamper-proof version history.

```
atrun publish --dist-url crate:ripgrep@15.0.0       # first publish
atrun publish --dist-url crate:ripgrep@15.1.0       # auto-links to 15.0.0
```

You can also link explicitly to any record — useful for forks or cross-ecosystem ports:

```
atrun publish --dist-url npm:my-fork \
              --derived-from at://did:plc:original-author/dev.atrun.module/3mgxyz
```

Or suppress auto-linking:

```
atrun publish --dist-url npm:new-package --no-derived-from
```

## Supported ecosystems

| Ecosystem | Lockfile | Artifact | Installer | Shorthands |
|-----------|----------|----------|-----------|------------|
| Python | `pylock.toml` (via `uv export`) | `.whl` | `uv` | `gh:` |
| Node.js | `package-lock.json` | `.tgz` | `pnpm`, `bun`, `npm` | `gh:`, `npm:` |
| Rust | `Cargo.lock` | crate | `cargo` | `gh:`, `crate:` |

Ecosystem is auto-detected from the lockfile content or distribution URL. You can override with `--ecosystem python|node|rust`.

## Record format

Records use the `dev.atrun.module` [lexicon](lexicons/dev.atrun.module.json). A record contains:

| Field | Description |
|-------|-------------|
| `package` | Package name |
| `version` | Package version |
| `description` | Short description (from artifact metadata) |
| `license` | License identifier |
| `url` | Project URL |
| `ecosystem` | Target ecosystem (`pythonEcosystem`, `nodeEcosystem`, `rustEcosystem`) |
| `resolved` | Array of dependency entries with `packageName`, `packageVersion`, `hash`, `url` |
| `derivedFrom` | StrongRef to the previous version (uri + CID) |

Each dependency entry can also have a `dependencies` array (for frozen lockfile verification) and a `source` strongRef pointing to another atrun record.

## License

Apache-2.0
