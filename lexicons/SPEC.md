# dev.atpub Lexicon Specification

Record types for publishing versioned artifacts on AT Protocol. A manifest describes a collection of artifacts — software packages, documents, datasets, container images — with cryptographic digests, download URLs, and metadata. A yank record marks a previously published manifest as withdrawn.

Any AT Protocol client can create and read these records. The reference implementation is [atrun](https://github.com/halazar/at-run).

## Motivation

Artifacts — software packages, academic papers, datasets, container images — are published across many registries and hosting services. Each has its own metadata format, identity system, and discovery mechanism. A Python package on PyPI, a paper on arxiv, and a Docker image on Docker Hub have no common way to express what they are, who published them, or how to verify their contents.

This creates several problems:

**No portable publisher identity.** A PyPI account, an arxiv login, and a Docker Hub username are separate identities with no connection between them. There is no way to verify that the same person published a package and a paper, or to carry a reputation across registries.

**No content verification independent of the host.** Registries serve artifacts, but there is no publisher-signed statement of what the artifact's hash should be. If a registry is compromised or an artifact is tampered with in transit, consumers have no independent record to check against.

**No structured provenance.** Version histories, derivation chains, and relationships between artifacts are either implicit (same package name, incremented version number) or scattered across changelogs and release notes. There is no machine-readable, cryptographically-linked chain from one version to the next.

**No social layer.** Discussion about a package or paper happens on Twitter, Bluesky, blog posts, and mailing lists — disconnected from the artifact itself. There is no way to see engagement, commentary, or endorsements attached to a specific published version.

### Why AT Protocol

AT Protocol provides the infrastructure these problems require:

- **Decentralized identity (DIDs).** The publisher's identity is not tied to any single registry. A DID can publish a Python package, an academic paper, and a container image, and all three are verifiably from the same entity.
- **Content addressing (CIDs).** Every record is immutable and content-addressed. A manifest's CID is a permanent, verifiable reference to an exact statement about a set of artifacts.
- **Repository model.** Records live in the publisher's own repository, not a central database. No single service controls publication or access.
- **Social primitives.** Posts, likes, reposts, and replies are native to the protocol. Announcing a manifest via a Bluesky post gives it a discussion thread, engagement metrics, and social discovery — without building any of that infrastructure.
- **Open read access.** Any client can read public records via XRPC without authentication or API keys.

### Design Decisions

**A manifest is a collection of artifacts that reference one or more external resources** — package files, PDFs, tarballs, container images. A software package includes its dependencies. A paper includes supplementary materials. A container deployment includes multiple images. The `artifacts` array with a `root` index handles all of these uniformly — the root identifies the primary artifact, and everything else is part of the same package.

**Multiple URLs per artifact, all referencing the same content.** Each artifact's `urls` array can contain several URLs that all resolve to the provably byte-for-byte identical resource, verified by the artifact's `digest`. This provides redundancy (mirrors, CDNs, alternative registries) and flexibility in how the resource is addressed. URLs may be standard transport URLs like `https://` for direct download, or [Package URLs](https://github.com/package-url/purl-spec) (`pkg:pypi/cowsay@6.1`) that locate the resource within the context of today's archives and repositories. Clients may choose among the URLs based on their own preferences — a corporate environment might prefer its internal mirror, a purl-aware client might resolve the package URL to a specific registry, and any client can fall back to alternatives if one source is unavailable.

**Digests are per-artifact, not per-record.** Each artifact carries its own `digest` in `algo:hex` format. This allows verification of individual artifacts downloaded from any mirror or CDN, independent of the hosting service. The record itself is verified by AT Protocol's content addressing (CID).

**`packageType` uses `knownValues`, not a closed enum.** The set of content types is open-ended. The schema documents known types (Python packages, npm packages, documents, datasets, containers) but any string is valid. This allows new domains — arxiv papers, DICOM imaging studies, government datasets — to define their own types without modifying the schema.

**`metadata` is free-form.** Domain-specific fields vary enormously: MeSH terms for biomedical papers, engine constraints for Node packages, platform specifications for containers. A fixed schema cannot anticipate every domain. Free-form metadata with a convention for key naming (`camelCase`) and a reserved key for record references (`dev.atpub#ref`) keeps the core schema stable while allowing unlimited extensibility.

**`derivedFrom` is a cryptographic chain, not a version number.** Version numbers are conventions that vary by ecosystem. `derivedFrom` links to the exact CID of a predecessor record, creating a verifiable chain: anyone can confirm that v2 actually references the content of v1, not just a version string. This also supports non-linear derivation — a dataset derived from two source datasets, or a meta-analysis referencing multiple studies. Because each `derivedFrom` entry is a strong reference with a URI, clients can follow the chain — fetching each predecessor record, then its predecessors. How that chain is interpreted is application-defined: a package manager might walk it to find changelogs between versions, a citation tool might use it to build a provenance graph, or a journal might display the revision history of a paper.

**Multiple records can describe the same underlying work.** The same paper, dataset, or package may have manifest records published by different parties with different `packageType` values — a journal publisher, a PubMed aggregator, and a Semantic Scholar indexer might each publish a record for the same paper. These are independent records with different metadata and perspectives, not versions of each other. Shared identifiers in the artifact `id` field (DOIs, PMIDs, package URLs) are what connect them: any client can find all manifest records that reference the same DOI, regardless of who published them or what `packageType` they use.

**`version` is scoped to what the manifest describes, not the underlying work.** An author publishing a paper revision uses version to mean the paper's revision (v1, v2). A metadata aggregator like Crossref publishing a record about that paper uses version to mean their record's version (version of record, correction, update). A software registry uses version for the package release. The `packageType` tells consumers how to interpret the version field. The manifest schema assigns no special semantics to version strings — they are application-defined.

**Equality and equivalence are domain-specific.** The manifest provides mechanisms to describe, identify, and validate artifacts — `digest` for content verification, `id` for canonical identification, `urls` for location — but does not enforce a single definition of "same artifact." For software packages, two artifacts may need to be byte-identical, verified by matching digests. For academic papers, a DOI may be sufficient to identify the same work even when the PDF bytes differ across publishers (different watermarks, formatting, or rendering). For container images, a manifest digest identifies an exact build while the same source code could produce different images. Applications that consume manifests define and enforce the equivalence policies appropriate to their domain.

**Yanking is a separate record, not a field on the manifest.** This preserves the original manifest's CID — existing references to it remain valid. Yanking is reversible (delete the yank record to un-yank). And it separates the publication act from the withdrawal act, which may happen at different times and for different reasons. For academic papers, a yank record with a reason is a retraction notice that does not destroy the original publication.

## Record Types

| NSID | Key | Description |
|------|-----|-------------|
| `dev.atpub.manifest` | TID | A versioned collection of artifacts |
| `dev.atpub.yank` | TID | Withdrawal notice for a manifest |

## dev.atpub.manifest

A manifest record describes one or more artifacts published together under a package name and version. The record is stored in the publisher's AT Protocol repository, identified by their DID, and is content-addressed by its CID.

### Record Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `createdAt` | `datetime` | Yes | ISO 8601 timestamp of record creation |
| `package` | `string` (max 256) | No | Primary name or identifier (e.g. `cowsay`, `2301.08745`, `nginx`) |
| `version` | `string` (max 64) | No | Version string (e.g. `1.6.0`, `v2`, `3.1.0-alpine`) |
| `description` | `string` (max 10240) | No | Human-readable description or abstract |
| `license` | `string` (max 128) | No | SPDX license identifier or expression (e.g. `MIT`, `Apache-2.0`, `CC-BY-4.0`) |
| `url` | `uri` | No | Homepage or canonical URL |
| `packageType` | `string` | No | Type of content (see [Content Types](#content-types)) |
| `tool` | `string` (max 128) | No | Tool that created this record (e.g. `atrun@0.14.0`) |
| `metadata` | `object` | No | Free-form metadata (see [Metadata](#metadata)) |
| `root` | `integer` | No | Index of the primary artifact in the `artifacts` array |
| `artifacts` | `artifact[]` (max 2048) | No | The artifacts in this manifest |
| `derivedFrom` | `strongRef[]` (max 512) | No | Manifest records this one derives from |

### Artifact Fields

Each entry in the `artifacts` array describes a single downloadable artifact.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` (max 512) | Canonical identifier from the artifact's native system (DOI, purl, DICOM UID) |
| `name` | `string` (max 256) | Artifact name |
| `version` | `string` (max 64) | Artifact version |
| `digest` | `string` (max 256) | Content digest in `algo:hex` format (e.g. `sha256:abcdef...`) |
| `urls` | `uri[]` (max 32) | Download URLs for the same content; all must be byte-identical per the digest |
| `artifactType` | `string` (max 128) | Type of artifact (e.g. `wheel`, `tarball`, `pdf`, `oci-image`) |
| `dependencies` | `integer[]` (max 256) | Indices of direct dependencies in the `artifacts` array |
| `metadata` | `object` | Free-form metadata specific to this artifact |
| `ref` | `strongRef` | Reference to this artifact's own `dev.atpub.manifest` record, if it has one |

### Content Types

The `packageType` field uses an open set of known values. Any string is valid; the following are documented:

| Value | Description |
|-------|-------------|
| `dev.atpub.defs#pythonPackage` | Python package (PyPI) |
| `dev.atpub.defs#npmPackage` | Node.js package (npm) |
| `dev.atpub.defs#rustCrate` | Rust crate (crates.io) |
| `dev.atpub.defs#goModule` | Go module (proxy.golang.org) |
| `dev.atpub.defs#dataset` | Dataset |
| `dev.atpub.defs#document` | Document (paper, specification, report) |
| `dev.atpub.defs#container` | Container image (OCI) |

Third parties may define their own types using reverse-domain naming (e.g. `org.arxiv#paper`).

### Metadata

Both the record-level and artifact-level `metadata` fields are free-form objects. Keys use `camelCase` per AT Protocol conventions.

**Reserved key:** `dev.atpub#ref` holds a `com.atproto.repo.strongRef` (`{uri, cid}`) linking to a related AT Protocol record. This allows any object within metadata to reference another record — for example, linking an author entry to their profile record.

Common metadata by content type:

**Software packages:**
```json
{
  "engine": "node",
  "requiresPython": ">=3.10"
}
```

**Documents:**
```json
{
  "authors": [
    {
      "name": "Alice Smith",
      "orcid": "0000-0001-2345-6789",
      "dev.atpub#ref": {"uri": "at://did:plc:xyz/...", "cid": "bafyrei..."}
    }
  ],
  "abstract": "We show that...",
  "keywords": ["inner ear", "mammals"],
  "doi": "10.1002/ar.25534",
  "pmid": "38965777",
  "journal": "Anatomical Record",
  "volume": "309",
  "issue": "4",
  "pages": "1178-1184",
  "meshTerms": [
    {"term": "Ear, Inner", "major": true, "qualifiers": ["anatomy & histology"]}
  ],
  "grants": [
    {"id": "2051335", "agency": "NSF"}
  ]
}
```

**Container images:**
```json
{
  "platform": "linux/amd64"
}
```

### Version Chains

The `derivedFrom` field links a manifest to its predecessors as an array of strong references (`{uri, cid}`). This creates a cryptographically-linked version chain: each new version references the exact CID of the previous version.

Typical uses:
- **Software releases:** v1.1.0 derives from v1.0.0
- **Paper revisions:** v2 derives from v1
- **Derived datasets:** a processed dataset derives from its raw source

The chain is publisher-asserted and verifiable — anyone can confirm the referenced CID matches the actual content of the prior record.

### Digest Verification

The `digest` field on each artifact contains a content hash in `algo:hex` format. Clients can verify artifact integrity by downloading the URL and comparing hashes:

```
sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

Supported algorithms follow the convention of the artifact's ecosystem. `sha256` is the most common; `sha512` is also used (e.g. npm integrity hashes).

## dev.atpub.yank

A yank record marks a manifest as withdrawn. The original manifest record remains in the repository — it is not deleted. Clients should treat yanked manifests as unavailable for new consumers while still allowing existing users to access them.

### Record Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `subject` | `strongRef` | Yes | The `dev.atpub.manifest` record being yanked |
| `reason` | `string` (max 1024) | No | Why this version was yanked |
| `createdAt` | `datetime` | Yes | ISO 8601 timestamp of the yank |

### Semantics

- **Yank is reversible.** Deleting the yank record un-yanks the manifest.
- **Yank is not deletion.** The manifest record and its CID remain valid. Existing references (e.g. `derivedFrom` chains) are not broken.
- **Retractions.** For documents, a yank record with a reason serves as a retraction notice. The original document remains accessible but is marked as retracted.

## Examples

### Python Package

```json
{
  "$type": "dev.atpub.manifest",
  "createdAt": "2025-01-15T12:00:00Z",
  "package": "cowsay",
  "version": "6.1",
  "description": "The famous cowsay for Python",
  "license": "GPL-3.0-only",
  "url": "https://github.com/VaasuDevanwormo/cowsay",
  "packageType": "dev.atpub.defs#pythonPackage",
  "root": 0,
  "artifacts": [
    {
      "name": "cowsay",
      "version": "6.1",
      "digest": "sha256:a0a59cc5e4e1e4e5b3a2e4b5f6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5",
      "urls": ["pkg:pypi/cowsay@6.1"],
      "artifactType": "wheel"
    }
  ]
}
```

### Academic Paper

```json
{
  "$type": "dev.atpub.manifest",
  "createdAt": "2024-07-04T00:00:00Z",
  "package": "38965777",
  "version": "1",
  "description": "A morphometric comparison of the ductus reuniens in humans and guinea pigs, with a note on its evolutionary importance.",
  "url": "https://doi.org/10.1002/ar.25534",
  "packageType": "dev.atpub.defs#document",
  "metadata": {
    "authors": [
      {"name": "Christopher M Smith", "orcid": "0000-0001-9259-1079"},
      {"name": "Ian S Curthoys", "orcid": "0000-0002-9416-5038"},
      {"name": "Jeffrey T Laitman", "orcid": "0000-0002-9629-946X"}
    ],
    "abstract": "The mammalian inner ear contains the sensory organs responsible for balance...",
    "journal": "Anatomical Record",
    "doi": "10.1002/ar.25534",
    "pmid": "38965777",
    "meshTerms": [
      {"term": "Ear, Inner", "major": true, "qualifiers": ["anatomy & histology"]},
      {"term": "Biological Evolution", "major": true}
    ],
    "keywords": ["inner ear", "mammals", "sensory systems"]
  },
  "root": 0,
  "artifacts": [
    {
      "name": "ar.25534",
      "version": "1",
      "id": "doi:10.1002/ar.25534",
      "digest": "sha256:...",
      "urls": ["https://anatomypubs.onlinelibrary.wiley.com/doi/pdf/10.1002/ar.25534"],
      "artifactType": "pdf"
    }
  ]
}
```

### Yank (Retraction)

```json
{
  "$type": "dev.atpub.yank",
  "subject": {
    "uri": "at://did:plc:abc123/dev.atpub.manifest/3kf7xyz",
    "cid": "bafyreiv1..."
  },
  "reason": "Results could not be reproduced. See https://doi.org/10.xxxx/retraction for details.",
  "createdAt": "2026-03-09T14:00:00Z"
}
```

## AT Protocol Integration

### Identity

The publisher is identified by their DID (Decentralized Identifier). The record is stored in their AT Protocol repository and signed by their key material. No separate author identity system is needed — the publisher's DID is authoritative.

### Discovery

Records can be discovered through:
- **Direct reference:** AT URI (`at://did:plc:abc123/dev.atpub.manifest/3kf7xyz`)
- **Shorthand:** `@handle:package[@version]` resolved via `listRecords`
- **Social posts:** Bluesky posts embedding a link card to the record's XRPC URL
- **Listing:** `com.atproto.repo.listRecords` with collection `dev.atpub.manifest`

### Social Layer

When a manifest record is announced via a Bluesky post with an embedded link card, the post's engagement (likes, reposts, replies) becomes a discussion and discovery layer for the content. Reposts do not duplicate the record — they reference the original post's URI and CID.
