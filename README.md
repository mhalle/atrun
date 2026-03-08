# atrun

Social package distribution on AT Protocol.

> **Alpha experiment.** This project explores decentralized package distribution on AT Protocol. The ideas are sound but the implementation is very early — the schema, CLI, and record format will change without notice. Do not use this for production systems or anything you intend to maintain long-term. atrun has been tested most fully with the Python ecosystem; other ecosystems work but have seen less use. If you're interested in the direction, follow along, but don't build on it yet.

## Why

Package registries like PyPI, npm, and crates.io are centralized services that store both metadata and artifacts. They work well, but they're single points of control — for metadata, for identity, and for discovery.

atrun takes a different approach: it uses [AT Protocol](https://atproto.com/) (the protocol behind [Bluesky](https://bsky.app)) as a decentralized package registry. Package records live in users' personal data repositories, the same infrastructure that stores their social posts.

atrun is built on **atpub**, a [Lexicon](https://atproto.com/guides/lexicon) (AT Protocol's schema system) for describing software artifacts. The `dev.atpub.manifest` record type is a generic, ecosystem-agnostic manifest that can represent lockfiles (uv.lock, package-lock.json, Cargo.lock), container compositions, or any collection of artifacts. A manifest can describe just one package or a package with all its pinned dependencies — how these work in practice is part of the experiment. atrun is one application of the atpub lexicon — it uses `dev.atpub.manifest` records for package distribution, but other tools could use the same record format for different purposes (build provenance, supply chain auditing, dataset publishing).

Manifest records live in AT Protocol but aren't strictly part of Bluesky. They're stored in users' personal data repositories alongside — but independent of — their social posts. Bluesky posts can optionally embed a manifest record, linking it to the social graph where it can be commented on, liked, and reposted. This is how `atrun publish --post` works.

In practice, a developer or team would publish releases under a dedicated Bluesky handle (e.g. `@myproject-releases.bsky.social`). Other developers and automated systems could follow that handle to get notified of new releases, the same way they'd follow any other account. Bots could monitor release handles and trigger CI pipelines, update dependency dashboards, or cross-post announcements. The social graph becomes the subscription mechanism — no webhooks, RSS feeds, or polling APIs needed.

Reposting works as a genuine distribution mechanism, not just social signal. When someone reposts a release announcement, the embedded manifest record travels with it — the AT URI and CID are preserved, so anyone who installs from a repost gets the same cryptographically verified record as someone who saw the original. The CID ensures the record hasn't been altered. Reposts become a form of endorsement that carries verifiable provenance.

A `dev.atpub.manifest` record is a **signed manifest**. It doesn't contain code, it points to artifacts hosted elsewhere (GitHub Releases, PyPI, npm, crates.io) and adds:

- **Identity** — every record is tied to a DID (decentralized identifier), so you know who published it
- **Integrity** — every record has a CID (content hash) and dependency hashes for tamper detection
- **Provenance** — `derivedFrom` creates verifiable version chains, each locked by CID
- **Portability** — records aren't locked to one server; users can move between PDS instances

The manifest format is generic — the same record works for Python wheels, npm tarballs, Rust crates, container images, or any artifact. The ecosystem is inferred from URL patterns in the artifact entries, and the installer picks the right tool (uv, pnpm, cargo, docker) automatically.

### Architecture

AT Protocol has a layered architecture that maps naturally to package distribution:

- **PDS** (Personal Data Server) — stores your records. This is where atrun publishes today.
- **AppView** — aggregates and indexes records across all users. No AppView exists yet for `dev.atpub.manifest`. When one is built, it could provide search, discovery, dependency graphs, trust analysis, and supply chain monitoring across the entire network.

Today, atrun reads and writes directly to PDS instances. Anyone can publish. No AppView exists yet, but because all `dev.atpub.manifest` records are public and follow a common schema, AppViews could be built to:

- **Monitor software releases** across the entire network in real time
- **Analyze packages for security vulnerabilities** and flag suspicious changes
- **Track usage and adoption** across publishers and ecosystems
- **Verify interoperability** between packages and their declared dependencies
- **Provide search and discovery** — find packages by name, ecosystem, publisher, or social signals
- **Audit supply chains** — trace dependency graphs, detect version conflicts, identify unmaintained packages

Multiple competing AppViews could coexist — one focused on security auditing, another on discovery, another on enterprise compliance — each with its own policies and presentation, all reading the same underlying data.

Future capabilities include:

- **Dependency back-references** — each artifact's `ref` field can point to its own `dev.atpub.manifest` record on AT Protocol, creating a web of linked manifests across publishers. An AppView could traverse these references to build a full dependency graph where every node is a signed, verifiable record.
- **Repository self-verification** — the `[tool.atpub]` handle embedded in a project's config (pyproject.toml, package.json, Cargo.toml) is now used for session resolution, and a tool or AppView could verify that the handle publishing a manifest matches the handle declared in the source repository, providing another layer of authenticity beyond the AT Protocol signature.

## Install

atrun is a Python package that requires Python 3.12+. The easiest way to install it is with [uv](https://docs.astral.sh/uv/):

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

Sessions are stored per-handle under `~/.config/atrun/sessions/`, so you can be logged in to multiple accounts simultaneously. The last login is also saved as the default.

#### Per-project handles

Add a handle to your project config and atrun will use it automatically — no `--handle` flag needed:

**pyproject.toml:**
```toml
[tool.atpub]
handle = "myproject-releases.bsky.social"
```

**package.json:**
```json
{
  "atpub": { "handle": "myproject-releases.bsky.social" }
}
```

**Cargo.toml:**
```toml
[package.metadata.atpub]
handle = "myproject-releases.bsky.social"
```

atrun walks up from the current directory looking for these config files (stopping at `.git` boundaries), so it works from any subdirectory of your project.

#### Session resolution order

When publishing, yanking, or unyanking, atrun resolves credentials in this order:

1. `ATRUN_SESSION` env var (pre-built session JSON)
2. `ATRUN_HANDLE` + `ATRUN_APP_PASSWORD` env vars (fresh login)
3. `--handle` CLI flag
4. Project config discovery (pyproject.toml, package.json, Cargo.toml)
5. Default session (`~/.config/atrun/session.json`)

#### GitHub Actions

Set `ATRUN_HANDLE` and `ATRUN_APP_PASSWORD` as repository secrets. atrun performs a fresh login on each run — no need to store session tokens.

```yaml
- name: Publish to AT Protocol
  env:
    ATRUN_HANDLE: ${{ secrets.BLUESKY_HANDLE }}
    ATRUN_APP_PASSWORD: ${{ secrets.BLUESKY_APP_PASSWORD }}
  run: atrun publish --dist-url npm:mypackage@${{ github.ref_name }}
```

A full release workflow might look like:

```yaml
name: Release
on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv tool install atrun
      - name: Publish to AT Protocol
        env:
          ATRUN_HANDLE: ${{ secrets.BLUESKY_HANDLE }}
          ATRUN_APP_PASSWORD: ${{ secrets.BLUESKY_APP_PASSWORD }}
        run: atrun publish --dist-url gh:${{ github.repository }}@${{ github.event.release.tag_name }} --post
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

## Yanking

If a version needs to be withdrawn (security issue, broken release), you can yank it. Yanking creates a separate `dev.atpub.yank` record that marks the version as withdrawn — the original record stays intact, preserving version chains and CIDs.

```
atrun yank @alice.bsky.social:cowsay@1.6.0
atrun yank --reason "security vulnerability" @alice.bsky.social:cowsay@1.6.0
```

Yanked versions are skipped when resolving `@latest` and marked `[yanked]` in list output. Direct version references still work — yanking is advisory, not destructive.

To restore a yanked version:

```
atrun unyank @alice.bsky.social:cowsay@1.6.0
```

Both `yank` and `unyank` support `--handle` to specify which account to authenticate as, and respect the same session resolution chain as `publish`.

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

### How verification and installation work

Each ecosystem follows the same general pattern — download the artifact, verify its hash against the digest in the manifest record, then install using the ecosystem's native tool — but the details vary.

Please note that the validation performed by this implementation has not been exhaustively verified. This is an experimental implementation only. The protocol itself has multiple levels of validation that future implementations can take full advantage of.

#### Python

- **Verification:** The wheel is downloaded and its SHA256 (or SHA512) hash is computed and compared against the `digest` field in the manifest. If the hashes match, the verified artifact is used for installation via a `file://` URL. If no hash is available, atrun warns and installs directly from the remote URL.
- **Installation:** `uv tool install {package} @ {url}`. Dependencies are resolved by uv natively — the lockfile in the record captures the dependency snapshot at publish time, but uv handles resolution at install time.
- **Running:** `uvx --from {package} @ {url}` — installs into a temporary environment and executes.

#### Node.js

Node.js has the most thorough verification, with a two-stage process when dependency data is present:

- **Verification (with `--deps`):**
  1. atrun reconstructs a `pnpm-lock.yaml` from the artifact entries in the record, including integrity hashes (SHA512, SRI format) for every dependency.
  2. `pnpm install --frozen-lockfile` verifies all dependency hashes against the reconstructed lockfile.
  3. The main package is downloaded separately, its hash is verified against the manifest digest, and it is installed from the verified local file.
- **Verification (without `--deps`):** The main package tarball is downloaded, hash-verified, and installed directly via `{engine} install -g {url}`.
- **Installation:** Global install via the selected engine — `pnpm install -g` (default), `npm install -g`, or `bun install -g`. Choose with `--engine`.
- **Running:** `pnpm exec`, `npx`, or `bunx` depending on the engine.

#### Rust

- **Verification:** The crate is downloaded from crates.io into memory and its SHA256 hash is compared against the manifest digest. This is a pre-check — the artifact is not saved to disk.
- **Installation:** `cargo install {package}@{version}`. Cargo handles dependency resolution natively using its own lock mechanisms. The lockfile in the record captures the dependency snapshot but cargo resolves independently.
- **Running:** `cargo install --locked {package}@{version}` — the `--locked` flag tells cargo to use exact dependency versions.

#### Go

- **Verification:** Go module hashes in `go.sum` use the `h1:` format (base64-encoded SHA256 of the module zip). atrun converts these to standard `sha256:{hex}` format for the manifest. Verification is handled implicitly by Go's native tooling — `go install` checks modules against `go.sum` automatically.
- **Installation:** `go install {module}@{version}`. Go handles dependency resolution natively.
- **Running:** `go run {module}@{version}`.

#### Container

- **Verification:** Unlike other ecosystems, container verification queries the registry in real time. atrun calls `docker manifest inspect` (or `crane digest`) to get the current manifest digest and compares it against the SHA256 digest stored in the record. This catches cases where a tag has been re-pointed to a different image.
- **Installation:** `docker pull {image}@sha256:{digest}` — pulling by digest (not tag) ensures you get exactly the image that was published, regardless of tag mutations. With crane: `crane pull {image}@sha256:{digest}`.
- **Running:** `docker run --rm {image}@sha256:{digest}` — runs with the digest-pinned reference.
- **Image reference normalization:** Bare names like `nginx` are expanded to `docker.io/library/nginx:latest`. User names like `user/app` become `docker.io/user/app:latest`.

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
| `tool` | The tool that created this manifest (e.g. `atrun@0.15.0`) |
| `metadata` | Free-form object for ecosystem-specific data (e.g. `pythonVersion`, `engine`) |
| `artifacts` | Array of artifact entries (see below) |
| `derivedFrom` | StrongRef(s) to records this derives from (uri + CID) |

Each artifact entry has optional fields: `id`, `name`, `version`, `digest`, `url`, `artifactType`, `dependencies`, `metadata`, and `ref` (a strongRef to the artifact's own manifest record). While all fields are optional in the schema, artifacts are expected to provide a unique, dereferenceable, and verifiable descriptor of their resource. What that means depends on the application — Python and npm lockfiles use a combination of `name`, `url`, and `digest`; other applications may use a unique `id` and conventions for accessing the resource through it. Applications are responsible for enforcing these constraints for security and correctness.

## How atrun compares

atrun/atpub occupies a different point in the design space than existing package distribution systems.

**Traditional registries** (PyPI, npm, crates.io) are centralized services that store both metadata and artifacts. They handle identity (account systems), discovery (search), and distribution (hosting). They work well — but they're single points of control, and each one is ecosystem-specific. A Python developer and a Rust developer use completely different systems with different identities and different trust models.

**Sigstore / in-toto / SLSA** focus on supply chain attestation — proving *how* an artifact was built (build provenance, transparency logs, signing). These are complementary to atrun. atpub manifests could reference Sigstore signatures or SLSA provenance records in artifact metadata. atrun solves a different problem: *who* published something and *what* they published, with a decentralized identity layer.

**OCI / ORAS** generalized container registries to store any artifact type. Like atpub, they're ecosystem-agnostic. But OCI registries are still centralized infrastructure — you need to run or rent a registry. atpub records live in AT Protocol personal data repositories, with no dedicated infrastructure required beyond what already exists for Bluesky.

**IPFS / content-addressed systems** share atpub's emphasis on integrity (CIDs, content hashes). But IPFS focuses on content storage and retrieval. atpub doesn't store content at all — it stores signed metadata that *points to* content hosted elsewhere. The artifacts themselves stay on GitHub Releases, PyPI, npm, Docker Hub, wherever they already are.

**GitHub Releases / artifact hosting** provide download URLs but no structured metadata, no identity beyond the GitHub account, no dependency information, and no cross-ecosystem format. atpub adds a structured metadata layer on top of these existing hosting services.

What's different about atpub:
- **Cross-ecosystem** — one record format for Python, Node, Rust, Go, containers, datasets, anything
- **Decentralized identity** — publisher identity is a DID, not an account on a specific service
- **No artifact hosting** — manifests point to artifacts wherever they already live
- **Social distribution** — publication, description, announcement, and distribution through a large-scale, robust social media network. Package releases become native social objects that can be discussed, shared, and discovered alongside regular posts.
- **Portable** — records move with the user across PDS instances; no lock-in to a specific server

## License

Apache-2.0
