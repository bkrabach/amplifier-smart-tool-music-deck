#!/usr/bin/env bash
# =============================================================================
# pre-push-scan.sh — refuses a push that edits a locked contract
# =============================================================================
# WHY THIS EXISTS
#   A locked contract is the project's law. "Do not edit it" as an instruction
#   is a rule someone can follow; this is a rule that refuses. No person and no
#   AI session can change a locked contract in place — the push is rejected.
#   Changes arrive as a proposal beside the original instead.
#
# WHAT IT CHECKS
#   For every file in the push, if its first heading line contains "(FROZEN"
#   — either the version already on the remote or the version being pushed —
#   the file is LOCKED. A locked file may only move if the same push also
#   contains a proposal beside it: <stem>*-candidate.md in the same folder
#   (the legacy CANDIDATE-*.md name is also accepted).
#
# HOW TO INSTALL (per repository, once)
#   mkdir -p .githooks && cp docs/workspace-template/pre-push-scan.sh .githooks/pre-push
#   chmod +x .githooks/pre-push
#   git config core.hooksPath .githooks
#
# HOW TO RUN BY HAND
#   ./pre-push-scan.sh              # compare HEAD against its upstream
#   ./pre-push-scan.sh origin/main  # compare HEAD against a named base
#   Exit 0 = clean. Exit 1 = refused, with each locked file named.
#
# THE ESCAPE HATCH IS NOT A BYPASS
#   Adding a proposal file lets the push through so a candidate can be written
#   and discussed. It does not ratify anything. Only the intent steward's word
#   turns a candidate into law, and only then does the original text change.
# =============================================================================

set -euo pipefail

ZERO="0000000000000000000000000000000000000000"
EMPTY_TREE="$(git hash-object -t tree /dev/null)"

# --- collect the ranges being pushed: one "BASE HEAD" pair per line ----------
ranges=""

resolve_base() {
  # resolve_base <head_sha> — best pre-image when the remote has no such ref yet
  local head="$1" oldest parent
  oldest="$(git rev-list "$head" --not --remotes 2>/dev/null | tail -1 || true)"
  if [ -n "$oldest" ]; then
    parent="$(git rev-parse --verify --quiet "${oldest}^" || true)"
    [ -n "$parent" ] && { printf '%s' "$parent"; return; }
  fi
  printf '%s' "$EMPTY_TREE"
}

# Git invokes a pre-push hook with the remote NAME and URL as arguments and the
# refs on stdin. So stdin decides the mode: refs present means hook mode, and the
# arguments are ignored. A hand run has a terminal on stdin and may name a base.
if [ ! -t 0 ]; then
  while read -r _local_ref local_sha _remote_ref remote_sha; do
    [ -n "${local_sha:-}" ] || continue
    [ "$local_sha" = "$ZERO" ] && continue          # branch deletion: nothing to scan
    if [ "${remote_sha:-$ZERO}" = "$ZERO" ]; then
      base="$(resolve_base "$local_sha")"
    else
      base="$remote_sha"
    fi
    ranges="${ranges}${base} ${local_sha}"$'\n'
  done
fi

# No refs on stdin means this was not a push, or was a push of nothing. Fall back
# to comparing HEAD against a named base, or against its upstream. This fallback
# does NOT require a terminal: a hand run whose stdin is a pipe must still scan,
# never quietly report success.
if [ -z "$ranges" ]; then
  head_sha="$(git rev-parse --verify --quiet HEAD || true)"
  [ -n "$head_sha" ] || { echo "pre-push-scan: no commits yet — nothing to scan"; exit 0; }
  if [ "$#" -ge 1 ] && [ -n "${1:-}" ] && [ "$1" != "--" ]; then
    base="$(git rev-parse --verify --quiet "$1^{commit}" || true)"
    [ -n "$base" ] || { echo "pre-push-scan: cannot resolve base ref '$1' — refusing" >&2; exit 1; }
  else
    base="$(git rev-parse --verify --quiet '@{u}' || true)"
    [ -n "$base" ] || base="$(resolve_base "$head_sha")"
  fi
  ranges="$base $head_sha"
fi

# --- scan each range ---------------------------------------------------------
refusals=""

while read -r base head; do
  [ -n "${base:-}" ] || continue                    # blank line from the range list
  if [ -z "${head:-}" ]; then
    echo "pre-push-scan: could not work out what is being pushed ('$base')" >&2
    echo "Refusing rather than passing a push it could not read." >&2
    exit 1
  fi
  changed="$(git diff --name-only "$base" "$head" -- '*.md')"
  [ -n "$changed" ] || continue

  # A file is LOCKED for this push if, at any single commit in the push, the
  # version it was edited FROM already carried "(FROZEN". Checking the parent of
  # each commit — not just the far end of the range — means the steward can still
  # lock a draft (its parent was a draft), while a push that locks a file in one
  # commit and edits it in the next is still caught.
  if [ "$base" = "$EMPTY_TREE" ]; then
    commits="$(git rev-list --no-merges "$head")"
  else
    commits="$(git rev-list --no-merges "${base}..${head}")"
  fi

  locked=""
  while IFS= read -r c; do
    [ -n "$c" ] || continue
    p="$(git rev-parse --verify --quiet "${c}^" || printf '%s' "$EMPTY_TREE")"
    touched="$(git diff --name-only "$p" "$c" -- '*.md')"
    while IFS= read -r tf; do
      [ -n "$tf" ] || continue
      case "${tf##*/}" in *-candidate.md|CANDIDATE-*.md) continue ;; esac
      git show "$p:$tf" 2>/dev/null | grep -m1 '^# ' | grep -q '(FROZEN' || continue
      case "$locked" in *"|$tf|"*) ;; *) locked="${locked}|${tf}|"$'\n' ;; esac
    done <<< "$touched"
  done <<< "$commits"

  [ -n "$locked" ] || continue

  while IFS= read -r f; do
    f="${f#|}"; f="${f%|}"
    [ -n "$f" ] || continue
    bn="${f##*/}"

    dir="$(dirname "$f")"
    stem="${bn%.md}"; stem="${stem%%.v*}"
    hatch=""
    while IFS= read -r c; do
      [ -n "$c" ] || continue
      [ "$(dirname "$c")" = "$dir" ] || continue
      cb="${c##*/}"
      case "$cb" in
        "$stem"*-candidate.md|CANDIDATE-*.md) hatch="$c"; break ;;
      esac
    done <<< "$changed"

    [ -n "$hatch" ] && continue
    refusals="${refusals}  ${f}"$'\n'
  done <<< "$locked"
done <<< "$ranges"

if [ -n "$refusals" ]; then
  {
    echo "REFUSED: this push edits a locked contract."
    echo ""
    printf '%s' "$refusals"
    echo ""
    echo "A locked contract (its heading carries \"(FROZEN\") never changes in place."
    echo "Propose the change instead: add a sibling file beside it named"
    echo "  <contract>.vN-candidate.md"
    echo "with three parts, in order — the exact change, sentence by sentence; the"
    echo "evidence (a cost paid or a failure caught; preference is not evidence);"
    echo "and what does NOT change. Include that file in the same push."
    echo ""
    echo "The original stays the law until the intent steward ratifies."
  } >&2
  exit 1
fi

echo "pre-push-scan: clean — no locked contract edited"
exit 0
