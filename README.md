# atrun

Social package distribution on AT Protocol.

> **Alpha experiment.** This project explores decentralized package distribution on AT Protocol. The ideas are sound but the implementation is very early — the schema, CLI, and record format will change without notice. Do not use this for production systems or anything you intend to maintain long-term. If you're interested in the direction, follow along, but don't build on it yet.

## Why

Package registries like PyPI, npm, and crates.io are centralized services that store both metadata and artifacts. They work well, but they're single points of control — for metadata, for identity, and for discovery.

atrun takes a different approach: it uses [AT Protocol](https://atproto.com/) (the protocol behind [Bluesky](https://bsky.app)) as a decentralized package registry. Package records live in users' personal data repositories, the same infrastructure that stores their social posts.

atrun is built on **atpub**, a [Lexicon](https://atproto.com/guides/lexicon) (AT Protocol's schema system) for describing software artifacts. The `dev.atpub.manifest` record type is a generic, ecosystem-agnostic manifest that can represent lockfiles (uv.lock, package-lock.json, Cargo.lock), container compositions, or any collection of artifacts. atrun is one application of the atpub lexicon — it uses `dev.atpub.manifest` records for package distribution, but other tools could use the same record format for different purposes (build provenance, supply chain auditing, dataset publishing).

A `dev.atpub.manifest` record is a **signed manifest**. It doesn't contain code, it points to artifacts hosted elsewhere (GitHub Releases, PyPI, npm, crates.io) and adds:

- **Identity** — every record is tied to a DID (decentralized identifier), so you know who published it
- **Integrity** — every record has a CID (content hash) and dependency hashes for tamper detection
- **Provenance** — `derivedFrom` creates verifiable version chains, each locked by CID
- **Portability** — records aren't locked to one server; users can move between PDS instances
- **Social distribution** — records can be embedded in Bluesky posts, making package announcements native to the social network

The manifest format is generic — the same record works for Python wheels, npm tarballs, Rust crates, container images, or any artifact. The ecosystem is inferred from URL patterns in the artifact entries, and the installer picks the right tool (uv, pnpm, cargo, docker) automatically.

### Architecture

AT Protocol has a layered architecture that maps naturally to package distribution:

- **PDS** (Personal Data Server) — stores your records. This is where atrun publishes today.
- **AppView** — aggregates and indexes records across all users. No AppView exists yet for `dev.atpub.manifest`. When one is built, it could provide search, discovery, dependency graphs, trust analysis, and supply chain monitoring across the entire network.

Today, atrun reads and writes directly to PDS instances. Anyone can publish. When AppViews exist, they will decide how to present and index records. Multiple competing AppViews could coexist — one focused on security auditing, another on discovery, another on enterprise compliance.

## Install

atrun requires [uv](https://docs.astral.sh/uv/) and Python 3.12+. Install uv first if you don't have it:

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then install atrun:

```
uv tool install atrun
```

This installs `atrun` into an isolated environment and adds it to `~/.local/bin`. Make sure that directory is in your PATH:

```
export PATH="$HOME/.local/bin:$PATH"
```

Add that line to your shell profile (`~/.zshrc`, `~/.bashrc`, etc.) to make it permanent.

### Ecosystem prerequisites

Only the tools for ecosystems you plan to use are required:

- **Python** — [uv](https://docs.astral.sh/uv/) (already installed above)
- **Node.js** — [pnpm](https://pnpm.io/) (recommended), [bun](https://bun.sh/), or [npm](https://www.npmjs.com/). For pnpm, run `pnpm setup` after installing to configure the global bin directory.
- **Rust** — [cargo](https://doc.rust-lang.org/cargo/) (via [rustup](https://rustup.rs/))
- **Go** — [go](https://go.dev/dl/)
- **Container** — [docker](https://docs.docker.com/get-docker/) or [crane](https://github.com/google/go-containerregistry/tree/main/cmd/crane)

## Quick start

Most commands (`info`, `list`, `install`, `run`, `resolve`, `verify`, `fetch`) work without authentication. You only need to log in to publish.

### Authenticate

To publish packages, create an [app password](https://bsky.app/settings/app-passwords) on Bluesky, then:

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
atrun publish --dist-url go:github.com/junegunn/fzf            # latest Go module
atrun publish --dist-url go:github.com/junegunn/fzf@v0.60.3    # specific version
atrun publish --dist-url docker:ghcr.io/user/app:1.0.0         # container image
atrun publish --dist-url docker:nginx:1.25                      # Docker Hub image
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

Using the `@handle:package` shorthand:

```
atrun install @alice.bsky.social:cowsay
atrun install @alice.bsky.social:cowsay@1.6.0
```

All URL formats also work:

```
atrun install at://did:plc:abc123/dev.atpub.manifest/3mgxyz
atrun install 'https://bsky.social/xrpc/com.atproto.repo.getRecord?repo=did:plc:abc123&collection=dev.atpub.manifest&rkey=3mgxyz'
atrun install https://bsky.app/profile/alice.bsky.social/post/3mgxyz
```

Choose a Node.js package manager:

```
atrun install --engine bun @alice.bsky.social:cowsay
atrun install --engine npm @alice.bsky.social:cowsay
```

Control dependency verification:

```
atrun install --deps @alice.bsky.social:cowsay      # require frozen lockfile verification
atrun install --no-deps @alice.bsky.social:cowsay   # skip verification, let the package manager resolve
```

### List packages

List all packages published by a user:

```
atrun list @alice.bsky.social
```

```
@alice.bsky.social:atrun@0.12.0 (python)
@alice.bsky.social:ripgrep@15.1.0 (rust)
@alice.bsky.social:cowsay@1.6.0 (node)
```

List all versions of a specific package:

```
atrun list @alice.bsky.social:atrun
```

```
@alice.bsky.social:atrun@0.12.0  (2026-03-07T05:29:18Z)
@alice.bsky.social:atrun@0.11.0  (2026-03-07T05:19:09Z)
@alice.bsky.social:atrun@0.9.0   (2026-03-07T04:56:02Z)
```

Every line is a usable shorthand — copy-paste it into `atrun install` or `atrun info`.

### Inspect a record

```
atrun info @alice.bsky.social:ripgrep
```

```
package: ripgrep
version: 15.1.0
packageType: dev.atpub.defs#rustCrate
description: ripgrep is a line-oriented search tool...
license: Unlicense OR MIT
url: https://github.com/BurntSushi/ripgrep
digest: sha256:f388c4955f85477c28a8667355819844a06614b083c23517f0e86bd1d6d82b73
dependencies: 1

publisher: alice.bsky.social (did:plc:abc123)
timestamp: 2026-03-07T05:02:29.773027Z
cid: bafyreihddco5gubbss4vmhe4464zb47kt4p4lzmp5acy766o3alxvrjoam
```

Structured JSON:

```
atrun info --json @alice.bsky.social:ripgrep
```

Full raw record from the PDS:

```
atrun info --raw @alice.bsky.social:ripgrep
```

Follow the version chain (via `derivedFrom` links):

```
atrun info --versions @alice.bsky.social:atrun
```

```
* @alice.bsky.social:atrun@0.12.0  (2026-03-07T05:29:18Z)
  @alice.bsky.social:atrun@0.11.0  (2026-03-07T05:19:09Z)
  @alice.bsky.social:atrun@0.9.0   (2026-03-07T04:56:02Z)
  @alice.bsky.social:atrun@0.8.0   (2026-03-07T04:38:44Z)
```

Social context (publisher profile, post engagement):

```
atrun info --social @alice.bsky.social:cowsay
```

Get the distribution URL for use with other tools:

```
uv add $(atrun info --dist @alice.bsky.social:mypackage)
pnpm install $(atrun info --dist @alice.bsky.social:cowsay)
```

Registry metadata (from PyPI, npm, or crates.io):

```
atrun info --registry @alice.bsky.social:ripgrep
```

### Resolve dependencies

Print dependencies in the ecosystem's native format:

```
atrun resolve @alice.bsky.social:mypackage
```

### Verify an artifact

Check the digest of a published artifact without installing:

```
atrun verify @alice.bsky.social:ripgrep
```

### Fetch artifacts

Download artifacts to a local directory:

```
atrun fetch @alice.bsky.social:mypackage
atrun fetch --deps @alice.bsky.social:mypackage       # include all dependencies
atrun fetch --dir ./downloads @alice.bsky.social:mypackage
```

### Run a package

Install into a temporary environment and execute:

```
atrun run @alice.bsky.social:cowsay
```

## Version chains

When you publish a new version of a package, atrun automatically links it to the previous version via `derivedFrom` — a cryptographically verified back-reference (AT URI + CID). This creates a tamper-proof version history.

```
atrun publish --dist-url crate:ripgrep@15.0.0       # first publish
atrun publish --dist-url crate:ripgrep@15.1.0       # auto-links to 15.0.0
```

View the chain:

```
atrun info --versions @alice.bsky.social:ripgrep
```

Link explicitly to any record — useful for forks or cross-ecosystem ports:

```
atrun publish --dist-url npm:my-fork \
              --derived-from @bob.bsky.social:original-package
```

Or suppress auto-linking:

```
atrun publish --dist-url npm:new-package --no-derived-from
```

## Addressing

atrun accepts multiple address formats everywhere a record is referenced:

| Format | Example |
|--------|---------|
| Shorthand | `@alice.bsky.social:cowsay` |
| Shorthand with version | `@alice.bsky.social:cowsay@1.6.0` |
| AT URI | `at://did:plc:abc123/dev.atpub.manifest/3mgxyz` |
| XRPC URL | `https://bsky.social/xrpc/com.atproto.repo.getRecord?repo=...` |
| Bluesky post URL | `https://bsky.app/profile/alice.bsky.social/post/3mgxyz` |
| Plain HTTPS (with `--unsigned`) | `https://example.com/record.json` |

The `@handle:package` shorthand is the most human-friendly. It resolves to the latest version by default, or a specific version with `@version`.

## Supported ecosystems

| Ecosystem | Lockfile | Artifact | Installer | Shorthands |
|-----------|----------|----------|-----------|------------|
| Python | `pylock.toml` (via `uv export`) | `.whl` | `uv` | `gh:` |
| Node.js | `package-lock.json` | `.tgz` | `pnpm`, `bun`, `npm` | `gh:`, `npm:` |
| Rust | `Cargo.lock` | crate | `cargo` | `gh:`, `crate:` |
| Go | `go.sum` | module zip | `go` | `go:` |
| Container | `compose.yml`, `.images` | OCI image | `docker`, `crane` | `docker:` |

Ecosystem is auto-detected from the lockfile content or distribution URL. You can override with `--ecosystem python|node|rust|go|container`.

## Record format

Records use the `dev.atpub.manifest` [lexicon](lexicons/dev.atpub.manifest.json). A record contains:

| Field | Description |
|-------|-------------|
| `package` | Package name |
| `version` | Package version |
| `description` | Short description (from artifact metadata) |
| `license` | License identifier |
| `url` | Project URL |
| `packageType` | Open enum: `dev.atpub.defs#pythonPackage`, `#npmPackage`, `#rustCrate`, `#goModule`, `#dataset`, `#document`, `#container` |
| `tool` | The tool that created this manifest (e.g. `atrun@0.14.3`) |
| `metadata` | Free-form object for ecosystem-specific data (e.g. `pythonVersion`, `engine`) |
| `artifacts` | Array of artifact entries (see below) |
| `derivedFrom` | StrongRef(s) to records this derives from (uri + CID) |

Each artifact entry has optional fields: `id`, `name`, `version`, `digest`, `url`, `artifactType`, `dependencies`, `metadata`, and `ref` (a strongRef to the artifact's own manifest record). While all fields are optional in the schema, artifacts are expected to provide a unique, dereferenceable, and verifiable descriptor of their resource. What that means depends on the application — Python and npm lockfiles use a combination of `name`, `url`, and `digest`; other applications may use a unique `id` and conventions for accessing the resource through it. Applications are responsible for enforcing these constraints for security and correctness.

## License

Apache-2.0
