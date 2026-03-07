"""Docker/OCI container ecosystem support."""

from __future__ import annotations

import json
import re
import subprocess

LOCKFILE_EXTENSIONS = [".yml", ".yaml", ".images"]
SUPPORTED_ENGINES = ("docker", "crane")
DEFAULT_ENGINE = "docker"


def _parse_image_ref(ref: str) -> dict:
    """Parse a container image reference into components.

    Handles:
      - bare name: nginx -> docker.io/library/nginx:latest
      - user/name: user/app -> docker.io/user/app:latest
      - full: ghcr.io/user/app:v2 -> ghcr.io/user/app:v2
      - digest: image@sha256:abc -> image@sha256:abc
    """
    ref = ref.strip()

    # Handle digest references
    if "@sha256:" in ref:
        name, digest = ref.split("@", 1)
        result = _parse_image_name(name)
        result["digest"] = digest
        result["tag"] = None
        return result

    # Handle tag references
    result = _parse_image_name(ref)
    return result


def _parse_image_name(ref: str) -> dict:
    """Parse image name and tag, normalizing bare names."""
    # Split tag
    tag = "latest"
    # A colon after a slash indicates a tag; a colon before any slash is registry:port
    last_colon = ref.rfind(":")
    if last_colon > ref.rfind("/"):
        tag = ref[last_colon + 1:]
        ref = ref[:last_colon]

    # Normalize: bare name -> docker.io/library/name
    # user/name (no dots in first segment) -> docker.io/user/name
    parts = ref.split("/")
    if len(parts) == 1:
        registry = "docker.io"
        name = f"library/{ref}"
    elif len(parts) == 2 and "." not in parts[0] and ":" not in parts[0]:
        registry = "docker.io"
        name = ref
    else:
        registry = parts[0]
        name = "/".join(parts[1:])

    return {
        "registry": registry,
        "name": f"{registry}/{name}",
        "tag": tag,
        "digest": None,
    }


def _build_image_ref(entry: dict) -> str:
    """Build a digest-pinned image reference from a resolved entry."""
    name = entry["name"]
    hash_str = entry.get("hash", "")
    if hash_str.startswith("sha256:"):
        return f"{name}@{hash_str}"
    return f"{name}:{entry.get('version', 'latest')}"


def _build_oci_url(name: str, tag: str) -> str:
    """Build an oci:// URL from image name and tag."""
    return f"oci://{name}:{tag}"


def _resolve_digest(image_ref: str, engine: str = DEFAULT_ENGINE) -> str:
    """Resolve an image reference to its manifest digest.

    Uses docker manifest inspect or crane digest.
    Returns sha256:hex string.
    """
    if engine == "crane":
        cmd = ["crane", "digest", image_ref]
    else:
        cmd = ["docker", "manifest", "inspect", "--verbose", image_ref]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise SystemExit(f"{engine} not found. Install {engine} to work with container images.")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Failed to resolve digest for {image_ref}: {exc.stderr.strip()}")

    if engine == "crane":
        return result.stdout.strip()

    # Parse docker manifest inspect output for digest
    try:
        data = json.loads(result.stdout)
        if isinstance(data, list):
            data = data[0]
        digest = data.get("Descriptor", {}).get("digest", "")
        if not digest:
            # Try alternative format
            digest = data.get("digest", "")
        if digest:
            return digest
    except (json.JSONDecodeError, KeyError):
        pass

    raise SystemExit(f"Could not extract digest from {engine} output for {image_ref}")


def parse_lockfile(content: str) -> list[dict]:
    """Parse a compose YAML or .images text file into dependency entries.

    Compose YAML: files with a 'services' key containing image values.
    .images: one image ref per line.
    """
    entries = []

    # Try YAML (compose file)
    try:
        import yaml
        data = yaml.safe_load(content)
        if isinstance(data, dict) and "services" in data:
            for _svc_name, svc in data["services"].items():
                image = svc.get("image")
                if not image:
                    continue
                parsed = _parse_image_ref(image)
                name = parsed["name"]
                tag = parsed["tag"] or "latest"
                digest = parsed.get("digest") or _resolve_digest(f"{name}:{tag}")
                entries.append({
                    "name": name,
                    "version": tag,
                    "hash": digest,
                    "url": _build_oci_url(name, tag),
                })
            entries.sort(key=lambda e: e["name"])
            return entries
    except Exception:
        pass

    # Plain text: one image ref per line
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = _parse_image_ref(line)
        name = parsed["name"]
        tag = parsed["tag"] or "latest"
        digest = parsed.get("digest") or _resolve_digest(f"{name}:{tag}")
        entries.append({
            "name": name,
            "version": tag,
            "hash": digest,
            "url": _build_oci_url(name, tag),
        })

    entries.sort(key=lambda e: e["name"])
    return entries


def export_lockfile() -> str:
    """Read compose.yml or docker-compose.yml from the current directory."""
    from pathlib import Path

    for name in ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"):
        p = Path(name)
        if p.exists():
            return p.read_text()

    raise SystemExit("No compose.yml or docker-compose.yml found in current directory.")


def build_metadata() -> dict:
    """Return ecosystem-specific metadata."""
    return {"engine": DEFAULT_ENGINE}


def generate_install_args(record: dict, engine: str = DEFAULT_ENGINE) -> list[str]:
    """Build docker pull command args for a record's images."""
    resolved = record.get("resolved", [])
    if not resolved:
        raise SystemExit("No resolved images in record.")
    # Pull the main package image by digest
    package = record.get("package")
    entry = next((e for e in resolved if e["name"] == package), resolved[0])
    ref = _build_image_ref(entry)
    return [engine, "pull", ref]


def generate_run_args(record: dict, engine: str = DEFAULT_ENGINE) -> list[str]:
    """Build docker run command args."""
    resolved = record.get("resolved", [])
    if not resolved:
        raise SystemExit("No resolved images in record.")
    package = record.get("package")
    entry = next((e for e in resolved if e["name"] == package), resolved[0])
    ref = _build_image_ref(entry)
    return [engine, "run", "--rm", ref]


def fetch_metadata(url: str) -> dict:
    """Fetch metadata from an OCI image via docker inspect."""
    # Parse oci:// URL
    ref = url.removeprefix("oci://")
    result: dict[str, str] = {"Name": ref}

    try:
        out = subprocess.run(
            ["docker", "inspect", ref],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(out.stdout)
        if isinstance(data, list) and data:
            data = data[0]
        config = data.get("Config", {})
        labels = config.get("Labels", {}) or {}
        if "org.opencontainers.image.description" in labels:
            result["Description"] = labels["org.opencontainers.image.description"]
        if "org.opencontainers.image.url" in labels:
            result["URL"] = labels["org.opencontainers.image.url"]
        if "org.opencontainers.image.version" in labels:
            result["Version"] = labels["org.opencontainers.image.version"]
    except Exception:
        pass

    return result


def extract_dist_metadata(url: str) -> dict:
    """Extract standardized metadata from an OCI image URL."""
    meta = fetch_metadata(url)
    result: dict[str, str] = {}
    if "Description" in meta:
        result["description"] = meta["Description"]
    if "URL" in meta:
        result["url"] = meta["URL"]
    return result


def verify_digest(image_ref: str, expected_hash: str, engine: str = DEFAULT_ENGINE) -> bool:
    """Verify an image's current digest matches the expected hash.

    Returns True if they match, raises SystemExit on mismatch.
    """
    actual = _resolve_digest(image_ref, engine)
    if actual != expected_hash:
        raise SystemExit(
            f"Digest mismatch for {image_ref}: "
            f"expected {expected_hash[:20]}... got {actual[:20]}..."
        )
    return True


def format_resolve_output(resolved: list[dict]) -> str:
    """Format resolved images for output."""
    lines = []
    for entry in resolved:
        lines.append(f"{entry['name']}:{entry['version']}")
    return "\n".join(lines)
