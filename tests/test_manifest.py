"""The manifest is reachable from the library and agrees with the package.

Contracts served: ``cli.v1`` Core 7 ("the manifest is exposed as structured data
via ``music_deck.manifest()``"), plus the Smart Tools spec's manifest rules that
the upstream conformance kit also enforces -- asserted here too so a break shows
up in ``pytest`` rather than only in the kit.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from music_deck.manifest import ManifestError, manifest, manifest_body, split_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[1]

_INSTALL_COMMAND_VERBS = (
    "pip",
    "pip3",
    "pipx",
    "uv",
    "npm",
    "npx",
    "brew",
    "apt",
    "apt-get",
    "curl",
    "wget",
    "sudo",
    "cargo",
    "go",
    "gem",
    "make",
    "docker",
)


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def test_manifest_is_a_dict_naming_the_tool():
    """cli.v1 Core 7: `music_deck.manifest()` is the structured accessor."""
    result = manifest()
    assert isinstance(result, dict)
    assert result["name"] == "music-deck"


def test_manifest_version_matches_the_package_definition():
    """The kit compares these two strings; so does this test, for a faster signal."""
    assert manifest()["version"] == _pyproject_version() == "0.1.0"


def test_manifest_fields_are_exactly_the_closed_set():
    """Spec: fields not listed in the schema are not part of the manifest."""
    allowed = {
        "smart_tool_format",
        "name",
        "version",
        "description",
        "use_cases",
        "platforms",
        "requires",
    }
    result = manifest()
    assert set(result) <= allowed
    assert allowed - {"requires"} <= set(result)


def test_manifest_field_shapes():
    result = manifest()
    assert isinstance(result["smart_tool_format"], int)
    for field in ("name", "version", "description"):
        assert isinstance(result[field], str) and result[field].strip()
    for field in ("use_cases", "platforms"):
        assert isinstance(result[field], list) and result[field]
        assert all(isinstance(item, str) and item.strip() for item in result[field])


def test_name_is_lowercase_alphanumeric_and_hyphens():
    import re

    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", manifest()["name"])


def test_requires_entries_reference_documentation_never_a_command():
    """Spec: install is a reference to documentation, never a command."""
    for entry in manifest().get("requires", []):
        assert set(entry) <= {"name", "purpose", "install", "optional"}
        for field in ("name", "purpose", "install"):
            assert isinstance(entry[field], str) and entry[field].strip()
        install = entry["install"]
        assert not any(character.isspace() for character in install)
        assert install.split("/")[0].split()[0] not in _INSTALL_COMMAND_VERBS


def test_requires_install_paths_exist_in_the_repository():
    """A doc reference that points nowhere is a broken promise to the reader."""
    for entry in manifest().get("requires", []):
        install = entry["install"]
        if install.startswith(("http://", "https://")):
            continue
        assert (REPO_ROOT / install).is_file(), f"{install} does not exist"


def test_exactly_one_manifest_under_the_distribution_root():
    """Spec: exactly one manifest per distribution."""
    skip = {
        ".git",
        ".private",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
    }
    found = [
        path
        for path in REPO_ROOT.rglob("SMART_TOOL.md")
        if not set(path.relative_to(REPO_ROOT).parts) & skip
    ]
    assert len(found) == 1, f"expected one SMART_TOOL.md, found {found}"


def test_descriptor_names_the_manifest_and_the_smoke_verb():
    """packaging.md: the descriptor is how a host finds and launches the tool."""
    import json

    descriptor = json.loads((REPO_ROOT / "smart-tool.json").read_text(encoding="utf-8"))
    assert descriptor["manifest"] == "src/music_deck/SMART_TOOL.md"
    assert (REPO_ROOT / descriptor["manifest"]).is_file()
    assert descriptor["cli_argv"] == ["music-deck"]
    assert descriptor["deterministic_smoke"] == ["check"]


def test_manifest_body_is_present_and_separate_from_the_frontmatter():
    body = manifest_body()
    assert body.startswith("# music-deck")
    assert "smart_tool_format" not in body


@pytest.mark.parametrize(
    "text, reason",
    [
        ("no fence here\n", "does not begin with a fence"),
        ("---\nname: x\nstill open\n", "fence is never closed"),
    ],
)
def test_a_broken_frontmatter_fence_raises_rather_than_half_parsing(text, reason):
    with pytest.raises(ManifestError):
        split_frontmatter(text)
