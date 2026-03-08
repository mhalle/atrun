"""Convert old shorthand specifiers to Package URLs."""

from __future__ import annotations

from packageurl import PackageURL


_SHORTHAND_TO_PURL_TYPE = {
    "pypi:": "pypi",
    "npm:": "npm",
    "crate:": "cargo",
    "go:": "golang",
    "docker:": "docker",
    "gh:": "github",
}


def from_shorthand(spec: str) -> str:
    """Convert old shorthand to a purl string.

    Examples:
        pypi:requests@2.31       -> pkg:pypi/requests@2.31
        npm:@scope/pkg@1.0       -> pkg:npm/%40scope/pkg@1.0
        go:golang.org/x/text@v0.14 -> pkg:golang/golang.org/x/text@v0.14
        gh:owner/repo@tag        -> pkg:github/owner/repo@tag
        docker:ghcr.io/user/app:1.0 -> pkg:docker/ghcr.io/user/app@1.0
    """
    for prefix, purl_type in _SHORTHAND_TO_PURL_TYPE.items():
        if spec.startswith(prefix):
            rest = spec[len(prefix):]
            return _convert(purl_type, rest)
    raise ValueError(f"Unknown shorthand prefix: {spec}")


def _convert(purl_type: str, rest: str) -> str:
    if purl_type == "github":
        return _convert_github(rest)
    if purl_type == "golang":
        return _convert_golang(rest)
    if purl_type == "npm":
        return _convert_npm(rest)
    if purl_type == "docker":
        return _convert_docker(rest)
    # Simple case: pypi, cargo
    return _convert_simple(purl_type, rest)


def _convert_simple(purl_type: str, rest: str) -> str:
    """Convert name@version to purl."""
    if "@" in rest:
        name, version = rest.rsplit("@", 1)
    else:
        name, version = rest, None
    return PackageURL(type=purl_type, name=name, version=version).to_string()


def _convert_npm(rest: str) -> str:
    """Convert npm specifier, handling scoped packages."""
    if rest.startswith("@"):
        # Scoped: @scope/pkg@version
        scope_and_pkg, *ver_parts = rest.split("/", 1)
        if not ver_parts:
            return PackageURL(type="npm", namespace=scope_and_pkg, name=scope_and_pkg).to_string()
        pkg_part = ver_parts[0]
        if "@" in pkg_part:
            name, version = pkg_part.rsplit("@", 1)
        else:
            name, version = pkg_part, None
        return PackageURL(type="npm", namespace=scope_and_pkg, name=name, version=version).to_string()
    return _convert_simple("npm", rest)


def _convert_golang(rest: str) -> str:
    """Convert go module specifier with namespace splitting."""
    if "@" in rest:
        module, version = rest.rsplit("@", 1)
    else:
        module, version = rest, None
    # Split into namespace (all but last segment) and name (last segment)
    if "/" in module:
        parts = module.rsplit("/", 1)
        namespace, name = parts[0], parts[1]
    else:
        namespace, name = None, module
    return PackageURL(type="golang", namespace=namespace, name=name, version=version).to_string()


def _convert_github(rest: str) -> str:
    """Convert gh:owner/repo@tag."""
    if "@" in rest:
        repo, version = rest.rsplit("@", 1)
    else:
        repo, version = rest, None
    if "/" in repo:
        namespace, name = repo.split("/", 1)
    else:
        namespace, name = None, repo
    return PackageURL(type="github", namespace=namespace, name=name, version=version).to_string()


def _convert_docker(rest: str) -> str:
    """Convert docker:image:tag, using colon-separated tag as version."""
    # Find the tag: last colon that is after the last slash
    last_slash = rest.rfind("/")
    colon_after_slash = rest.rfind(":")
    if colon_after_slash > last_slash and last_slash >= 0:
        image, version = rest[:colon_after_slash], rest[colon_after_slash + 1:]
    elif colon_after_slash > 0 and last_slash < 0:
        # No slash, but has colon: e.g. nginx:1.25
        image, version = rest[:colon_after_slash], rest[colon_after_slash + 1:]
    else:
        image, version = rest, None
    # Split into namespace and name
    if "/" in image:
        namespace, name = image.rsplit("/", 1)
    else:
        namespace, name = None, image
    return PackageURL(type="docker", namespace=namespace, name=name, version=version).to_string()
