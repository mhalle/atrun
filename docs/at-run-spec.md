# atrun: Social Package Distribution on AT Protocol

## The Idea

`atrun` publishes Python lockfiles as signed records on AT Protocol (the protocol behind Bluesky). Each record is a list of package names, versions, SHA-256 hashes, and source URLs — everything needed to reproduce a Python environment exactly. The record is signed by the publisher's decentralized identity (DID), carried through the federated network, and addressable as a social object.

The result is that a `uv.lock` file, which normally sits quietly in a git repo, becomes a first-class social object that can accumulate discussion, security labels, trust signals, and community review — without changing what the lockfile contains or how the developer works.

## What It Does

**Publishing:** You have a Python project. You run `uv lock` and `uv build`. The `atrun publish` command reads the lockfile, extracts each dependency's name, version, hash, and source URL, sorts them deterministically, and writes the list as an AT Protocol record to your Bluesky PDS. Your built wheel is uploaded to GitHub Releases (or PyPI, or anywhere with a URL), and included in the list like any other package.

**Running:** Someone else runs `atrun run at://alice.bsky.social/dev.atpub.manifest/3jvz2442yt32g`. The tool fetches the record, generates a `requirements.txt` with `--hash` pins for every entry, and hands it to `uv pip install --require-hashes`. UV downloads everything from the specified sources, verifies every hash, installs into a temporary environment, and runs the entry point. The runner never interprets any code — it just reshapes JSON into a format UV already understands.

## What the Record Looks Like

The record is deliberately minimal. It carries no commentary, no description, no name. It is a lockfile and nothing more.

```json
{
  "$type": "dev.atpub.manifest",
  "createdAt": "2026-03-06T12:00:00Z",
  "pythonVersion": "3.12",
  "platform": "linux-x86_64",
  "resolved": [
    {
      "name": "myproject",
      "version": "1.0.0",
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "url": "https://github.com/alice/myproject/releases/download/v1.0.0/myproject-1.0.0-py3-none-any.whl"
    },
    {
      "name": "anyio",
      "version": "4.2.0",
      "sha256": "745db742c8e9f8bcd2aa304e42e3211a02dfc860fbc01ce51adc4d27c27d03d4",
      "url": "https://files.pythonhosted.org/packages/.../anyio-4.2.0-py3-none-any.whl"
    },
    {
      "name": "httpx",
      "version": "0.27.0",
      "sha256": "a]0cb88a46f32dc874e04ee956e4c2764aba2aa228f650b06788ba6bda2962ab5",
      "url": "https://files.pythonhosted.org/packages/.../httpx-0.27.0-py3-none-any.whl"
    }
  ]
}
```

The `resolved` array is sorted alphabetically by `name` to ensure deterministic serialization. AT Protocol's DAG-CBOR encoding handles everything else for canonical content addressing.

The publisher's own project is just another entry in the list. It is not special. UV discovers entry points from the installed wheel's metadata, so the record does not need to declare them.

## Why AT Protocol

AT Protocol provides several things that matter for this use case, without any custom infrastructure:

**Signed identity.** Every record is in a repository controlled by a DID with cryptographic signing keys. The publisher's identity is verifiable. Unlike PyPI, where account compromise can be silent, an AT Proto record is tied to a DID with a visible history.

**Social graph.** Bluesky's follow relationships, which already exist for millions of users, become a trust layer for software. If you follow someone and they publish a module, that's a meaningful signal — more meaningful than an anonymous download count on a package registry.

**Labeling.** AT Protocol has a built-in labeling system for distributed moderation. A labeler service can watch for module records and flag those containing hashes that appear in vulnerability databases. Users subscribe to labelers they trust, just as they do for content moderation on Bluesky.

**Social interaction.** Any AT Protocol record can receive replies, quotes, likes, and reposts. A module record automatically becomes a place where discussion can happen. Bug reports, reviews, and security notices can be threaded against the record, attached to its specific set of hashes, signed by identifiable participants.

**The firehose.** AT Protocol's relay streams every new record in real time. Services can watch for new module publications, advisories, or label changes and act on them immediately. Cache invalidation becomes a non-problem: content-addressed artifacts never go stale, and the firehose tells you when new records are published.

**Federation.** Records are not hosted by a single server. They live on the publisher's PDS, are replicated through relays, and cached by anyone who fetches them. There is no single point of failure for distribution.

## What the System Does Not Do

**It does not host code.** No blobs, no artifacts, no source code stored on AT Protocol. The record is a manifest — a list of hashes and URLs. The code lives on PyPI, GitHub, npm, crates.io, or wherever it already lives.

**It does not resolve dependencies.** UV does all dependency resolution at publish time. The record contains the already-resolved result. There is no version solving, no constraint satisfaction, no compatibility checking at run time.

**It does not replace package registries.** PyPI still hosts Python packages. npm still hosts JavaScript packages. This system is a signed social layer on top of existing infrastructure, not a replacement for it.

**It does not manage versions.** There is no version chain, no "latest" pointer, no upgrade mechanism. Each record is a frozen, immutable snapshot. If the publisher releases a new version, that is a new record with a new set of hashes. The old record still works forever.

## How It Relates to UV

The entire system is a thin adapter between UV's lockfile and AT Protocol's record format. The transformation is mechanical:

**Publishing:** `uv.lock` TOML → sorted JSON array → AT Proto record (via `com.atproto.repo.createRecord`)

**Running:** AT Proto record → `requirements.txt` with `--hash` pins → `uv pip install --require-hashes` → `uv run`

No interpretation. No intelligence. The publishing tool is a format converter. The runner is a format converter. UV does all the real work.

The developer's workflow does not change. They write Python, run `uv lock`, run `uv build`, and optionally run `atrun publish`. The AT Protocol publication is an additive step, not a replacement for anything in the existing toolchain.

## What Emerges from Publishing Lockfiles Socially

Once lockfiles exist as signed social objects, several things become possible without additional protocol design:

**Security auditing as a social service.** A labeler watches the firehose for new module records, cross-references every hash against vulnerability databases, and labels records containing known-bad hashes. Users subscribe to the labeler. No CVE tracking infrastructure needed — the labeling system already exists.

**Smoke testing as a social service.** A testing service watches the firehose, fetches new module records, installs them in a sandbox, exercises the entry points, and publishes results as replies or labels. The module accumulates test attestations from independent parties.

**Compatibility evidence.** Every published module record implicitly attests that its set of hashes work together. If 200 records include httpx `abc123` and anyio `def456`, that is empirical evidence of compatibility. An AppView can aggregate this into a compatibility matrix without anyone explicitly declaring compatibility.

**Provenance tracking.** A `derivedFrom` field (optional, not in the minimal prototype) can point to the record a module was based on. Forks become visible. The social graph shows who modified whose work.

**Content-addressed caching.** Because every artifact is identified by hash, any cache — a CDN, a corporate proxy, a local disk, a BitTorrent swarm — can store artifacts keyed by hash. The hash verifies integrity regardless of where the bytes came from. The AT Proto record tells you which hashes you need; the cache provides speed.

**Auto-upgrade services.** A bot watches for new package releases, cross-references them against published module records, and notifies publishers when a dependency they use has a new version. Or it goes further: builds a new resolved set with the updated dependency, tests it, and publishes the result as a proposed replacement. The publisher reviews and decides.

**Ecosystem-wide impact analysis.** When a vulnerability is discovered in a package, an AppView can instantly identify every published module record that includes that hash. Not "projects that might be affected based on version ranges" but "records that definitely contain this exact artifact."

## The Prototype

The minimum viable implementation is two scripts:

### `atrun login`

Prompts for the user's Bluesky handle and app password. Creates a session via `com.atproto.server.createSession`. Saves the session string to `~/.config/atrun/session.txt` with restricted permissions. The app password is used once and not stored.

### `atrun publish`

1. Reads the saved session
2. Reads `uv.lock` from the current directory
3. For each package entry, extracts: name, version, hash, source URL
4. Sorts entries by package name
5. Calls `com.atproto.repo.createRecord` with collection `dev.atpub.manifest`
6. Prints the AT URI of the published record

### `atrun run <at-uri>`

1. Fetches the record from the publisher's PDS (no authentication needed — records are public)
2. Reads the `resolved` array
3. Generates a temporary `requirements.txt` with pinned versions and hash verification
4. Creates a temporary virtual environment
5. Runs `uv pip install --require-hashes -r requirements.txt`
6. Runs the root package's entry point

### GitHub Action

```yaml
on:
  push:
    tags: ['v*']
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv lock
      - run: uv build
      - run: gh release create ${{ github.ref_name }} dist/*.whl
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      - run: uv run atrun publish .
        env:
          ATRUN_SESSION: ${{ secrets.ATRUN_SESSION }}
```

## What This Is Not

This is not a new package manager. It is not trying to replace pip, UV, npm, or cargo. It is not trying to host code. It is not trying to build a new registry.

It is a thin social layer that takes something developers already produce — a resolved, hashed, pinned lockfile — and publishes it as a signed record on a federated social protocol. The lockfile becomes addressable, discussable, auditable, and discoverable. Everything else that makes this interesting — the security labels, the trust signals, the caching, the compatibility evidence — emerges from that one act of publication.

The implementation is almost trivial. The implications are not.

## Prior Art and Novelty

Several systems have explored pieces of this design individually:

- **Unison** uses content-addressed code where functions are identified by the hash of their implementation, enabling conflict-free dependency management.
- **gx** (IPFS) provided content-addressed package management on a decentralized network but lacked identity and social infrastructure, and was abandoned.
- **Nix** uses content-addressed store paths for reproducible builds but has no social layer.
- **DRPM** uses DIDs and Decentralized Web Nodes for npm package distribution.

The specific combination proposed here — publishing lockfiles as signed social objects on a protocol with an existing social graph, labeling system, and real-time event stream, while pointing to existing package registries rather than replacing them — does not appear in any existing system or published proposal.

## Lexicon

```json
{
  "lexicon": 1,
  "id": "dev.atpub.manifest",
  "defs": {
    "main": {
      "type": "record",
      "key": "tid",
      "record": {
        "type": "object",
        "required": ["createdAt", "resolved"],
        "properties": {
          "createdAt": {
            "type": "string",
            "format": "datetime"
          },
          "pythonVersion": {
            "type": "string",
            "maxLength": 32
          },
          "platform": {
            "type": "string",
            "maxLength": 64
          },
          "resolved": {
            "type": "array",
            "items": { "type": "ref", "ref": "#depEntry" },
            "maxLength": 2048
          },
          "derivedFrom": {
            "type": "string",
            "format": "at-uri"
          }
        }
      }
    },
    "depEntry": {
      "type": "object",
      "required": ["name", "version", "sha256", "url"],
      "properties": {
        "name": {
          "type": "string",
          "maxLength": 256
        },
        "version": {
          "type": "string",
          "maxLength": 64
        },
        "sha256": {
          "type": "string",
          "maxLength": 64
        },
        "url": {
          "type": "string",
          "format": "uri"
        },
        "hint": {
          "type": "string",
          "format": "at-uri"
        }
      }
    }
  }
}
```