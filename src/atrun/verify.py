"""Download and verify artifact hashes before install/run.

Provides hash utilities and download-and-verify functions for ensuring
artifact integrity against manifest records. Supports any algorithm
available in hashlib (sha256, sha512, etc.) via the "algo:hex" format
used throughout atrun records.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import httpx

SUPPORTED_ALGORITHMS = {"sha256", "sha512", "sha384", "sha1", "md5"}


def _parse_hash(hash_str: str) -> tuple[str, str]:
    """Parse an "algo:hex" hash string into (algorithm, hex_digest).

    If no algorithm prefix is present, defaults to sha256.
    """
    if ":" in hash_str:
        algo, hex_digest = hash_str.split(":", 1)
    else:
        algo, hex_digest = "sha256", hash_str
    if algo not in SUPPORTED_ALGORITHMS:
        raise ValueError(f"Unsupported hash algorithm: {algo}")
    return algo, hex_digest


def hash_bytes(data: bytes, algorithm: str = "sha256") -> str:
    """Return the hex digest of raw bytes using the given algorithm."""
    return hashlib.new(algorithm, data).hexdigest()


def hash_file(path: Path, algorithm: str = "sha256") -> str:
    """Return the hex digest of a file using the given algorithm, read in chunks."""
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class HashMismatchError(Exception):
    """Raised when a downloaded artifact's hash does not match the expected hash."""

    def __init__(self, url: str, expected: str, actual: str):
        self.url = url
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Hash mismatch for {url}: "
            f"expected {expected[:16]}..., got {actual[:16]}..."
        )


def download_and_verify(url: str, expected_hash: str) -> Path:
    """Download an artifact to a temp file, verify its hash, and return the path.

    The expected_hash should be in "algo:hex" format (e.g. "sha256:abc123..."
    or "sha512:def456..."). A bare hex digest defaults to sha256.
    The caller is responsible for cleaning up the temp file.

    Raises HashMismatchError if the hash does not match.
    """
    algo, expected = _parse_hash(expected_hash)

    resp = httpx.get(url, follow_redirects=True)
    resp.raise_for_status()

    suffix = ""
    filename = url.rsplit("/", 1)[-1]
    if "." in filename:
        if filename.endswith(".tar.gz"):
            suffix = ".tar.gz"
        else:
            suffix = "." + filename.rsplit(".", 1)[-1]

    tmp = tempfile.NamedTemporaryFile(prefix="atrun-", suffix=suffix, delete=False)
    tmp.write(resp.content)
    tmp.close()

    actual = hash_bytes(resp.content, algo)
    if actual != expected:
        Path(tmp.name).unlink(missing_ok=True)
        raise HashMismatchError(url, f"{algo}:{expected}", f"{algo}:{actual}")

    return Path(tmp.name)


def download_to(url: str, dest: Path, expected_hash: str | None = None) -> Path:
    """Download an artifact to a specific path, optionally verifying its hash.

    If expected_hash is provided (in "algo:hex" format), verifies the hash
    and raises HashMismatchError on mismatch. The file is not written if
    verification fails.

    Returns the destination path.
    """
    resp = httpx.get(url, follow_redirects=True)
    resp.raise_for_status()

    if expected_hash:
        algo, expected = _parse_hash(expected_hash)
        actual = hash_bytes(resp.content, algo)
        if actual != expected:
            raise HashMismatchError(url, f"{algo}:{expected}", f"{algo}:{actual}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return dest


def verify_artifact(url: str, expected_hash: str) -> None:
    """Download an artifact to memory, verify its hash, and discard.

    The expected_hash should be in "algo:hex" format (e.g. "sha256:abc123..."
    or "sha512:def456..."). A bare hex digest defaults to sha256.
    Used for pre-checks where the file is not needed (e.g. Rust).

    Raises HashMismatchError if the hash does not match.
    """
    algo, expected = _parse_hash(expected_hash)

    resp = httpx.get(url, follow_redirects=True)
    resp.raise_for_status()

    actual = hash_bytes(resp.content, algo)
    if actual != expected:
        raise HashMismatchError(url, f"{algo}:{expected}", f"{algo}:{actual}")
