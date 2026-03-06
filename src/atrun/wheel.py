"""Extract metadata from a wheel without installing it."""

from __future__ import annotations

import io
import zipfile
from email.parser import Parser

import httpx


def fetch_wheel_metadata(url: str) -> dict[str, str | list[str]]:
    """Download a wheel and extract its METADATA as a dict.

    Returns a dict with standard metadata fields. Multi-value fields
    (like Requires-Dist) are returned as lists.
    """
    resp = httpx.get(url, follow_redirects=True)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        metadata_path = next(
            (n for n in zf.namelist() if n.endswith(".dist-info/METADATA")),
            None,
        )
        if not metadata_path:
            raise ValueError(f"No METADATA found in wheel at {url}")

        raw = zf.read(metadata_path).decode("utf-8")

    msg = Parser().parsestr(raw)

    # Single-value fields
    result: dict[str, str | list[str]] = {}
    single_fields = [
        "Name", "Version", "Summary", "Author", "Author-email",
        "License", "Home-page", "Requires-Python",
    ]
    for field in single_fields:
        value = msg.get(field)
        if value:
            result[field] = value

    # Multi-value fields
    requires = msg.get_all("Requires-Dist")
    if requires:
        result["Requires-Dist"] = requires

    classifiers = msg.get_all("Classifier")
    if classifiers:
        result["Classifier"] = classifiers

    project_urls = msg.get_all("Project-URL")
    if project_urls:
        result["Project-URL"] = project_urls

    # Description body
    body = msg.get_payload()
    if body and body.strip():
        result["Description"] = body.strip()

    return result
