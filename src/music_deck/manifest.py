"""The SMART_TOOL.md manifest, reachable from the library as structured data.

``cli.v1`` Core 7 says "the manifest is exposed as structured data via
``music_deck.manifest()`` and via ``music-deck manifest``". This module is that
accessor, and it is the only way to read the manifest: it reads the copy built
into the installed package via ``importlib.resources``, never a path relative to
a checkout, because install layouts differ and no filesystem path is portable.

There is one manifest and one copy of it, so the file a registry reads and the
dict this function returns cannot disagree.

The closed field set from the Smart Tools spec is enforced here --
``smart_tool_format``, ``name``, ``version``, ``description``, ``use_cases``,
``platforms``, ``requires`` -- because "fields not listed here are not part of
the manifest". A manifest that violates it raises rather than returning
something half-true.
"""

from __future__ import annotations

import importlib.resources
from typing import Any, Final

import yaml

MANIFEST_FILENAME: Final = "SMART_TOOL.md"

_ALLOWED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "smart_tool_format",
        "name",
        "version",
        "description",
        "use_cases",
        "platforms",
        "requires",
    }
)
# `requires` is the one field a tool with no prerequisites leaves out.
_REQUIRED_FIELDS: Final[frozenset[str]] = _ALLOWED_FIELDS - {"requires"}

_ALLOWED_REQUIRE_FIELDS: Final[frozenset[str]] = frozenset(
    {"name", "purpose", "install", "optional"}
)
_REQUIRED_REQUIRE_FIELDS: Final[tuple[str, ...]] = ("name", "purpose", "install")


class ManifestError(RuntimeError):
    """The manifest is missing, malformed, or breaks the closed field set."""


def manifest_text() -> str:
    """The raw SMART_TOOL.md text, from the copy built into the package."""
    resource = importlib.resources.files("music_deck").joinpath(MANIFEST_FILENAME)
    if not resource.is_file():
        raise ManifestError(
            f"{MANIFEST_FILENAME} is not reachable at music_deck/{MANIFEST_FILENAME}. "
            "The manifest must ship inside the installed package."
        )
    return resource.read_text(encoding="utf-8")


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(yaml_frontmatter, markdown_body)`` from a ``---``-fenced file."""
    lines = text.splitlines()
    start = 0
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    if start >= len(lines) or lines[start].strip().lstrip("\ufeff") != "---":
        raise ManifestError(
            f"{MANIFEST_FILENAME} must begin with a YAML frontmatter block fenced by "
            "'---' on its own line."
        )
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[start + 1 : i]), "\n".join(lines[i + 1 :]).strip()
    raise ManifestError(
        f"{MANIFEST_FILENAME} frontmatter is not closed by a second '---' line."
    )


def _check_requirement(entry: Any, index: int) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ManifestError(
            f"requires[{index}] must be a mapping, got {type(entry).__name__}."
        )
    extra = set(entry) - _ALLOWED_REQUIRE_FIELDS
    if extra:
        raise ManifestError(
            f"requires[{index}] declares fields not in the manifest schema: "
            f"{sorted(extra)}. Allowed: {sorted(_ALLOWED_REQUIRE_FIELDS)}."
        )
    for field in _REQUIRED_REQUIRE_FIELDS:
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ManifestError(
                f"requires[{index}].{field} must be a non-empty string."
            )
    optional = entry.get("optional")
    if optional is not None and not isinstance(optional, bool):
        raise ManifestError(f"requires[{index}].optional must be a boolean if present.")
    # The spec: `install` is a reference to documentation -- a relative path or a
    # URL -- never a command. The manifest is inert; reading it runs nothing.
    install = entry["install"].strip()
    if any(token in install for token in ("&&", "||", "|", ";", "$(", "`", ">", "<")):
        raise ManifestError(
            f"requires[{index}].install ({install!r}) contains shell metacharacters. "
            "install must reference documentation, never a command."
        )
    if any(character.isspace() for character in install):
        raise ManifestError(
            f"requires[{index}].install ({install!r}) contains whitespace. A doc "
            "reference is a bare relative path or URL."
        )
    # A folded YAML scalar keeps its trailing newline; each of these is one
    # string, so hand it over as one.
    result = {field: entry[field].strip() for field in _REQUIRED_REQUIRE_FIELDS}
    if optional is not None:
        result["optional"] = optional
    return result


def manifest() -> dict[str, Any]:
    """The manifest frontmatter as a plain dict -- the library accessor.

    ``cli.v1`` Core 7. The returned dict carries exactly the manifest's own
    fields, so ``music_deck.manifest()["name"]`` is the tool's name and nothing
    else has been folded in.
    """
    frontmatter, _body = split_frontmatter(manifest_text())
    try:
        data = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        raise ManifestError(
            f"{MANIFEST_FILENAME} frontmatter is not valid YAML: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ManifestError(
            f"{MANIFEST_FILENAME} frontmatter must be a mapping, got "
            f"{type(data).__name__}."
        )

    extra = set(data) - _ALLOWED_FIELDS
    if extra:
        raise ManifestError(
            f"{MANIFEST_FILENAME} declares fields not in the manifest schema: "
            f"{sorted(extra)}. Fields not listed in the spec are not part of the "
            "manifest."
        )
    missing = _REQUIRED_FIELDS - set(data)
    if missing:
        raise ManifestError(
            f"{MANIFEST_FILENAME} is missing required manifest fields: {sorted(missing)}."
        )

    if not isinstance(data["smart_tool_format"], int) or isinstance(
        data["smart_tool_format"], bool
    ):
        raise ManifestError("smart_tool_format must be an integer.")
    for field in ("name", "version", "description"):
        if not isinstance(data[field], str) or not data[field].strip():
            raise ManifestError(f"{field} must be a non-empty string.")
    for field in ("use_cases", "platforms"):
        value = data[field]
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            raise ManifestError(f"{field} must be a non-empty list of non-empty strings.")

    result: dict[str, Any] = {
        "smart_tool_format": data["smart_tool_format"],
        "name": data["name"],
        "version": data["version"],
        # A folded YAML scalar keeps its trailing newline; the manifest's
        # description is one string, so hand it over as one.
        "description": data["description"].strip(),
        "use_cases": list(data["use_cases"]),
        "platforms": list(data["platforms"]),
    }

    if "requires" in data:
        requires = data["requires"]
        if not isinstance(requires, list):
            raise ManifestError("requires must be a list of entries.")
        result["requires"] = [
            _check_requirement(entry, index) for index, entry in enumerate(requires)
        ]

    return result


def manifest_body() -> str:
    """The free-form Markdown guidance after the frontmatter.

    It carries no compatibility guarantee: nothing may depend on a particular
    sentence being present.
    """
    _frontmatter, body = split_frontmatter(manifest_text())
    return body
