"""Every remedy names something the reader actually has.

Contract served: ``cli.v1`` Core 4, as extended on 2026-09-05 --

    "A remedy -- and the manifest's ``install`` -- names what the reader HAS: a
    command their install method takes, or text the installed package carries.
    **Never a source-tree path.**"

and its conformance-kit assert:

    "Every path and command a remedy or ``install`` names resolves in an
    INSTALLED copy -- not only in the source tree."

Why this file exists
--------------------
The measured failure was not exotic. ``check``'s client-ID remedy and the
manifest's ``install`` both said ``docs/spotify-app.md``. That file is in the
repository; ``pyproject.toml`` ships ``packages = ["src/music_deck"]``, so it is
*not* in the wheel. The one reader who most needs the instructions -- somebody
who ran ``uv tool install`` and has no checkout anywhere -- was pointed at a file
that does not exist on their machine. Nothing failed loudly; the remedy simply
led nowhere.

Two rules, not two literals
---------------------------
This file deliberately does **not** grep for ``docs/spotify-app.md``. A test that
did would pass the day somebody wrote ``docs/troubleshooting.md`` instead. So:

* **Rule A -- no source-tree path.** Any file path a remedy names must resolve
  *inside the installed package*, asked through ``importlib.resources`` (which is
  layout-independent, so the answer is the same from a checkout and from a wheel).
  Absolute paths and URLs are exempt: those are the reader's own files and the
  open internet, not a checkout.
* **Rule B -- installable by the documented method.** Any installer command a
  remedy names must lead with the form music-deck's own documented install method
  takes. A ``uv tool install`` owns a virtualenv that ``uv pip install`` has no
  way to name, so a remedy offering only the pip form is unusable by exactly the
  reader it is written for.

Where the strings come from
---------------------------
Both a **runtime** sweep (provoke each refusal and read its ``remedy``) and a
**static** sweep (parse every module in the package and collect every string in a
remedy position). The static half matters most: it covers remedies no test
thought to provoke, so a remedy added later is checked the day it lands rather
than the day somebody remembers to extend this file.
"""

from __future__ import annotations

import ast
import importlib.resources
import json
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

from music_deck import setup_guide
from music_deck.errors import REMEDIES, MusicDeckError, remedy_for
from music_deck.manifest import manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "src" / "music_deck"


# --------------------------------------------------------------------------- #
# Rule A -- what counts as a path, and what counts as "the reader has it"
# --------------------------------------------------------------------------- #
_URL = re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)

# A relative path naming a file: at least one directory component, then a name
# with an extension. The lookbehind keeps it from firing inside an absolute path
# (`/home/u/.config/x.json`) or an environment expansion (`$XDG_CONFIG_HOME/x`),
# both of which name the reader's own files rather than a checkout.
_RELATIVE_FILE = re.compile(
    r"(?<![\w/@:.$-])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\.[A-Za-z0-9]{1,5})"
)


def _source_tree_directories() -> frozenset[str]:
    """The repository's own top-level directories, read from the repository.

    Derived, not typed out: a directory added later is covered without anybody
    editing this list.
    """
    return frozenset(
        entry.name
        for entry in REPO_ROOT.iterdir()
        if entry.is_dir() and not entry.name.startswith(".") and entry.name != "src"
    )


def _candidate_paths(text: str) -> set[str]:
    """Every relative file path, and every source-tree reference, in one string."""
    without_urls = _URL.sub(" ", text)
    found = set(_RELATIVE_FILE.findall(without_urls))
    # A reference to a top-level source-tree directory is a source-tree path even
    # without a file extension -- `see contracts/` is no more use to an installed
    # reader than `see docs/spotify-app.md` is.
    for directory in _source_tree_directories():
        for match in re.finditer(
            rf"(?<![\w/@:.$-])({re.escape(directory)}/[A-Za-z0-9_./-]*)", without_urls
        ):
            found.add(match.group(1))
    # A path at the end of a sentence picks up the full stop; a path in a list
    # picks up the comma. Neither is part of the path.
    return {token.rstrip(".,;:)\"'") for token in found if token.strip(".,;:)\"'")}


def _ships_in_the_package(candidate: str) -> bool:
    """Is this path reachable inside the installed package?

    Asked through ``importlib.resources``, the same way ``manifest.py`` reads
    SMART_TOOL.md -- so the answer does not depend on there being a checkout.
    """
    root = importlib.resources.files("music_deck")
    for relative in (candidate, candidate.removeprefix("music_deck/")):
        try:
            if root.joinpath(relative).is_file():
                return True
        except (OSError, ValueError):
            continue
    return False


def _path_offences(label: str, text: str) -> list[str]:
    offences = []
    for candidate in sorted(_candidate_paths(text)):
        if _ships_in_the_package(candidate):
            continue
        in_source_tree = (REPO_ROOT / candidate).exists()
        offences.append(
            f"{label}: names {candidate!r}, which is not reachable inside the "
            f"installed package"
            + (
                " -- it exists only in the source tree, so a reader who ran "
                f"`{setup_guide.INSTALL_COMMAND}` does not have it."
                if in_source_tree
                else " and does not exist anywhere."
            )
            + f"  Full string: {text!r}"
        )
    return offences


# --------------------------------------------------------------------------- #
# Rule B -- what counts as an installer command
# --------------------------------------------------------------------------- #
def _documented_install_prefix() -> str:
    """The documented install method, read from the one place that defines it."""
    return " ".join(setup_guide.INSTALL_COMMAND.split()[:3])


_INSTALLERS = re.compile(
    r"\b(uv tool install|uv pip install|uvx install|pipx install|pip install|"
    r"pip3 install|python -m pip install)\b"
)


def _installer_commands(text: str) -> list[str]:
    """The installer invocations a string names, in the order a reader meets them."""
    return [match.group(1) for match in _INSTALLERS.finditer(text)]


def _install_offences(label: str, text: str) -> list[str]:
    commands = _installer_commands(text)
    if not commands:
        return []
    documented = _documented_install_prefix()
    if commands[0] != documented:
        return [
            f"{label}: the first installer command it names is {commands[0]!r}, "
            f"but music-deck's documented install method is {documented!r} "
            f"({setup_guide.INSTALL_COMMAND}). A tool install owns a virtualenv "
            f"`uv pip install` cannot reach, so this remedy is unusable by the "
            f"reader who followed the documented install.  Full string: {text!r}"
        ]
    return []


# --------------------------------------------------------------------------- #
# Collecting the strings -- runtime
# --------------------------------------------------------------------------- #
def _walk_remedies(document: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Every ``remedy``/``findings``/``detail`` string in a result document."""
    if isinstance(document, dict):
        for key, value in document.items():
            here = f"{path}.{key}" if path else key
            if key in ("remedy", "detail", "install", "next_command") and isinstance(
                value, str
            ):
                yield here, value
            else:
                yield from _walk_remedies(value, here)
    elif isinstance(document, list):
        for index, item in enumerate(document):
            yield from _walk_remedies(item, f"{path}[{index}]")
    elif isinstance(document, str) and path.endswith("findings"):
        yield path, document


@pytest.fixture
def unconfigured(tmp_path, monkeypatch):
    """A state directory rigged so every conditional remedy in `check` fires."""
    config = tmp_path / "config"
    state = tmp_path / "state"
    state.mkdir(parents=True)
    monkeypatch.setenv("MUSIC_DECK_CONFIG_DIR", str(config))
    monkeypatch.setenv("MUSIC_DECK_STATE_DIR", str(state))
    for name in ("MUSIC_DECK_CLIENT_ID", "SPOTIFY_CLIENT_ID"):
        monkeypatch.delenv(name, raising=False)
    # A redirect URI that does not conform, so that finding fires too.
    monkeypatch.setenv("MUSIC_DECK_REDIRECT_URI", "http://localhost:8080")

    long_ago = datetime.now(timezone.utc) - timedelta(days=400)
    token = state / "token.json"
    token.write_text(
        json.dumps(
            {
                "access_token": "expired",
                "expires_at": long_ago.isoformat(),
                "refresh_token": "old",
                "authorized_at": long_ago.isoformat(),
                "scopes": ["user-read-private"],
            }
        ),
        encoding="utf-8",
    )
    os.chmod(token, 0o644)  # so the "mode is not 0600" remedy fires
    (state / "last-403.json").write_text(
        json.dumps({"observed_at": long_ago.isoformat(), "endpoint": "/v1/me"}),
        encoding="utf-8",
    )
    return config, state


def _runtime_strings(monkeypatch) -> list[tuple[str, str]]:
    """Provoke every refusal this package can raise, and take its remedy."""
    from music_deck import auth, intelligence
    from music_deck.check import check
    from music_deck.verbs.setup import normalize_client_id, setup

    collected: list[tuple[str, str]] = []

    # 1. the frozen code table, plus the fallback for a code with no entry
    collected += [(f"errors.REMEDIES[{code}]", text) for code, text in REMEDIES.items()]
    collected.append(("errors.remedy_for(<unknown>)", remedy_for("no_such_code")))

    # 2. every remedy, finding and detail `check` can report
    collected += [(f"check().{key}", value) for key, value in _walk_remedies(check())]

    # 3. every remedy `setup` can report, and the guide it carries
    collected += [(f"setup().{key}", value) for key, value in _walk_remedies(setup())]
    collected.append(("setup_guide.render()", setup_guide.render()))
    collected.append(("setup_guide.INSTALL_COMMAND", setup_guide.INSTALL_COMMAND))

    # 4. the manifest's `install` -- named by Core 4 alongside remedies
    for index, entry in enumerate(manifest().get("requires", [])):
        collected.append((f"manifest().requires[{index}].install", entry["install"]))

    # 5. the client-ID refusals
    for provoke in (lambda: auth.require_client_id(), lambda: normalize_client_id("x")):
        with pytest.raises(MusicDeckError) as caught:
            provoke()
        collected.append(("MusicDeckError.remedy", caught.value.remedy))

    # 6. all four `plan` preflight refusals (cli.v1 Core 3), each forced
    engine = intelligence.AmplifierIntelligence()
    cases = {
        "unknown provider": {"MUSIC_DECK_PROVIDER": "nope"},
        "pinned, no credential": {"MUSIC_DECK_PROVIDER": "openai"},
        "no provider at all": {},
    }
    for label, environment in cases.items():
        with monkeypatch.context() as patch:
            for name in intelligence.PROVIDER_CREDENTIAL_ENV:
                for variable in intelligence.PROVIDER_CREDENTIAL_ENV[name]:
                    patch.delenv(variable, raising=False)
            patch.delenv("MUSIC_DECK_PROVIDER", raising=False)
            for key, value in environment.items():
                patch.setenv(key, value)
            with pytest.raises(intelligence.NoModelSubstrate) as caught:
                engine.preflight()
            collected.append((f"preflight ({label})", caught.value.remedy))

    with monkeypatch.context() as patch:
        patch.setenv("ANTHROPIC_API_KEY", "x")
        patch.delenv("MUSIC_DECK_PROVIDER", raising=False)
        patch.setattr(intelligence, "missing_package", lambda provider: "anthropic")
        with pytest.raises(intelligence.NoModelSubstrate) as caught:
            engine.preflight()
        collected.append(("preflight (provider_sdk)", caught.value.remedy))

        patch.setattr(intelligence, "missing_package", lambda provider: None)
        patch.setattr(intelligence, "engine_installed", lambda: False)
        with pytest.raises(intelligence.NoModelSubstrate) as caught:
            engine.preflight()
        collected.append(("preflight (engine)", caught.value.remedy))

    return collected


# --------------------------------------------------------------------------- #
# Collecting the strings -- static, over every module in the package
# --------------------------------------------------------------------------- #
_REMEDY_RAISERS = {"MusicDeckError", "NoProviderError", "NoModelSubstrate"}

# A module-level constant whose name says it holds a remedy or an install
# command. `errors.REMEDIES` -- the frozen code table -- is keyed by `ErrorCode`
# attributes rather than the literal "remedy", so the dict rule below cannot see
# it; this one can, and it covers any table named the same way later.
_REMEDY_CONSTANT = re.compile(r"REMED(Y|IES)|INSTALL")


def _literal(node: ast.AST) -> str | None:
    """A string literal, including one written as adjacent implicit-joined parts."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):  # an f-string: keep its literal parts
        parts = [
            piece.value
            for piece in node.values
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str)
        ]
        return "".join(parts) if parts else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        if left is not None or right is not None:
            return (left or "") + (right or "")
    return None


def _static_strings() -> list[tuple[str, str]]:
    """Every string in a remedy position, in every module of the package.

    Three positions count: the ``remedy`` argument of a raiser (third positional
    or the keyword), a dict entry keyed ``remedy`` or ``install``, and every
    string inside a constant whose name says it holds a remedy or an install
    command -- which is how ``errors.REMEDIES``, the frozen code table, is found.
    """
    collected: list[tuple[str, str, str]] = []
    for module in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        # Relative to the checkout when there is one; absolute when this sweep
        # is pointed at an installed copy instead (which is how the lane proved
        # the rule against a real `uv tool install`, not only against `src/`).
        try:
            label = f"{module.relative_to(REPO_ROOT)}"
        except ValueError:
            label = str(module)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [
                    target.id for target in targets if isinstance(target, ast.Name)
                ]
                if any(_REMEDY_CONSTANT.search(name) for name in names) and node.value:
                    for inner in ast.walk(node.value):
                        text = _literal(inner) if isinstance(inner, ast.Constant) else None
                        if text and text.strip():
                            collected.append(
                                (f"{label}:{node.lineno} {names[0]}", text, "fragment")
                            )
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(
                    node.func, "attr", None
                )
                if name in _REMEDY_RAISERS:
                    positional = node.args[2:3]
                    keywords = [
                        kw.value for kw in node.keywords if kw.arg == "remedy"
                    ]
                    for argument in [*positional, *keywords]:
                        text = _literal(argument)
                        if text:
                            collected.append(
                                (f"{label}:{node.lineno} {name}", text, "remedy")
                            )
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value in ("remedy", "install")
                        and (text := _literal(value))
                    ):
                        collected.append(
                            (f"{label}:{node.lineno} dict", text, "remedy")
                        )
    return collected


def _static_remedies() -> list[tuple[str, str]]:
    """Only the strings a reader is handed **whole**.

    Rule B judges the command a reader tries FIRST, which is a property of the
    assembled remedy, not of a fragment. ``ENGINE_INSTALL_HINT_PIP`` is a
    deliberate secondary alternative spliced in after the documented form; asking
    it in isolation "does this lead with a tool install?" asks the wrong
    question. The assembled remedy is still checked -- the runtime sweep provokes
    it and reads what the reader actually sees.
    """
    return [
        (label, text)
        for label, text, position in _static_strings()
        if position == "remedy"
    ]


# --------------------------------------------------------------------------- #
# The tests
# --------------------------------------------------------------------------- #
def test_the_sweep_actually_finds_remedies():
    """A collector that quietly found nothing would make every test below pass."""
    static = _static_strings()

    assert len(static) >= 10, static
    assert _static_remedies(), "no whole remedy strings found at all"
    modules = {label.split(":")[0] for label, _, _ in static}
    # The three sources cli.v1 Core 4's kit assert names, by module.
    assert any("errors.py" in name for name in modules)
    assert any("check.py" in name for name in modules)
    assert any("intelligence.py" in name for name in modules)


def test_no_remedy_the_package_can_emit_names_a_source_tree_path(
    unconfigured, monkeypatch
):
    """Rule A, over every remedy provoked at runtime and found statically."""
    offences: list[str] = []
    population = [
        *_runtime_strings(monkeypatch),
        *[(label, text) for label, text, _ in _static_strings()],
    ]
    for label, text in population:
        offences += _path_offences(label, text)

    assert not offences, "\n".join(offences)


def test_every_install_command_a_remedy_names_is_one_the_documented_method_takes(
    unconfigured, monkeypatch
):
    """Rule B, over the same population."""
    offences: list[str] = []
    for label, text in [*_runtime_strings(monkeypatch), *_static_remedies()]:
        offences += _install_offences(label, text)

    assert not offences, "\n".join(offences)


def test_the_manifest_install_field_resolves_for_a_reader_with_no_checkout():
    """Core 4 names ``install`` explicitly, so it gets its own assertion."""
    for entry in manifest().get("requires", []):
        install = entry["install"]
        assert not _path_offences(f"manifest requires[{entry['name']}].install", install)
        assert _URL.match(install) or _ships_in_the_package(install), (
            f"requires[{entry['name']}].install is {install!r}: neither a URL nor a "
            "file the installed package carries."
        )


def test_the_rules_would_catch_the_defect_they_were_written_for():
    """The guard is only worth anything if it fails on the real defect.

    Both rules are exercised against the two strings actually measured on the
    installed copy of b7f7334, and against a *different* source-tree path -- so
    a future rewrite that merely stopped saying `docs/spotify-app.md` would not
    slip through.
    """
    assert _path_offences("x", "Set MUSIC_DECK_CLIENT_ID. See docs/spotify-app.md.")
    assert _path_offences("x", "Read contracts/cli.v1.md for the promise.")
    assert _path_offences("x", "See docs/troubleshooting.md.")  # never existed
    assert _install_offences("x", 'Install the extra: uv pip install "music-deck[anthropic]".')

    # And the corrected forms pass.
    assert not _path_offences("x", "Run `music-deck setup` for the steps.")
    assert not _path_offences("x", f"See {setup_guide.REPO_URL} for the steps.")
    assert not _path_offences("x", "The token is at /home/you/.local/state/x/token.json.")
    assert not _path_offences("x", "Put it in $XDG_CONFIG_HOME/music-deck/config.json.")
    assert not _install_offences("x", setup_guide.install_with("anthropic"))
    assert not _path_offences("x", "music_deck/SMART_TOOL.md ships in the package.")


def test_the_documented_install_method_is_defined_in_exactly_one_place():
    """Rule B is only meaningful if `install_with` and the manifest agree."""
    documented = _documented_install_prefix()

    assert setup_guide.install_with("anything").startswith(documented)
    assert setup_guide.REPO_URL in setup_guide.INSTALL_COMMAND
    # The manifest points a reader at the same repository the install command
    # names, so "where do I get this" has one answer.
    installs = [entry["install"] for entry in manifest().get("requires", [])]
    assert any(setup_guide.REPO_URL in install for install in installs)


def test_the_shipped_package_is_the_only_thing_an_install_carries():
    """Why Rule A is the right rule, asserted rather than assumed.

    ``pyproject.toml`` ships one directory. Anything outside it -- ``docs/``,
    ``contracts/``, ``README.md`` -- is in the repository and nowhere else, which
    is precisely why a remedy may not name it.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'packages = ["src/music_deck"]' in pyproject
    assert not _ships_in_the_package("docs/spotify-app.md")
    assert _ships_in_the_package("SMART_TOOL.md")
    assert _ships_in_the_package("setup_guide.py")


def test_the_setup_guide_travels_with_the_package_and_needs_no_checkout():
    """Core 4's other half: "text the installed package carries"."""
    module = importlib.resources.files("music_deck").joinpath("setup_guide.py")

    assert module.is_file()
    text = json.dumps(setup_guide.guide())
    assert not _path_offences("setup_guide.guide()", text)
    assert len(setup_guide.render()) > 1000  # the whole guide, not a stub
