# Standing rules for this repository

Read these before your first edit. They apply to every session — human,
Amplifier, or another tool's coding agent — and they are the same rules the
people here follow.

## Vocabulary

- **Intent steward** — the person who decides where this project is going.
  Their word is the law you obey.
- **Manager session** — the long-running AI session that runs the project's
  work on the steward's behalf: it plans, briefs, launches, verifies,
  integrates.
- **Worker session** — a short-lived AI session that takes one bounded piece
  of work in its own copy of the code and returns with proof. You are
  probably one.
- **Contract** — a short promise this project must keep, in `contracts/`. A
  contract is *locked* (heading carries `(FROZEN <date>)`) or *draft*. This
  repo has four: `cli.v1.md`, `boundary.v1.md`, `plan.v1.md`, and
  `refusals.v1.md` — all `(DRAFT)`.

## 1. Converge toward the vision and the contracts

`docs/VISION.md` says where this project is going. `contracts/` says what
must be true along the way. Everything you do moves the repository toward
them.

- **Work is derived, never invented.** Every change traces to the gap between
  a contract and what exists, or to feedback the steward gave. Name the
  contract your change serves, in one line, in the work item and in the
  commit message.
- **If the contract and the code disagree, the contract wins** — unless you
  have evidence the contract is wrong, in which case see rule 2.
- **If no contract covers what you are doing, stop and say so.** Do not
  invent the promise yourself. A missing contract is a decision for the
  steward.

## 2. Never edit a locked contract — propose instead

A file whose heading carries `(FROZEN <date>)` does not change in place. Not
for a typo, not "while I'm in there," not because the change is obviously
right.

To change one, add a sibling file named `<contract>.vN-candidate.md` with
three parts, in order:

1. **The exact change**, sentence by sentence.
2. **The evidence** — a cost actually paid or a failure actually caught.
   Preference is not evidence.
3. **What does *not* change.**

The original stays the law until the steward answers. A pre-push hook refuses
a push that edits a locked contract without a candidate beside it (see
`PINS.md`); if it refuses you, do not work around it — the refusal is the
rule working.

## 3. Where the contract check lives

The **ledger** at `ledger/rows.yaml` (not seeded yet) will record, one row
per checkable clause, whether that clause is currently *Kept · Not yet ·
Broken · Pinned open · Can't check*. It is derived from the contracts, never
hand-edited into agreement with the code.

Run the upstream Smart Tools kit for the whole repo:

```
uv run <path-to-amplifier-smart-tools>/conformance/run.py .
```

Per-contract kits live at `conformance/<contract>/run.py` — not built yet.

CI at `.github/workflows/ci.yml` builds wheel and source-distribution artifacts,
then runs `pytest -m 'not live'` and command smokes against installed copies
from a scratch directory with isolated HOME/XDG directories. It has no secrets
and makes no Spotify, account, provider, or model calls. The pinned upstream kit
must report exactly 15 pass, 0 fail, and 0 skip; ordinary pytest skips remain
separate and reported.

Public error codes and exit statuses come from `music_deck.errors`, matching
`contracts/refusals.v1.md`; do not maintain a second registry in a verb. Test
both caught library exceptions and CLI envelopes. At external failure boundaries,
retain only reviewed diagnostics, never raw messages, codes, or payloads that
may contain credentials.

Keep LAN observation separate from authenticated Spotify Web API behavior:
authenticate and complete the Web API read before any opt-in local traffic, and
never present discovery as playback support.

Publication privacy: use synthetic account/device fixtures, never identifiers
copied from live runs. GitHub handles, repository URLs, and GitHub noreply
attribution are permitted; personal emails, home paths, hostnames, and account
data are not. Keep raw evidence in `.private/`, excluded from Git and packages.
Before pushing, review file content, commit identities, history, and public
PR/CI text. Removing a value from HEAD does not remove it from history.

Rules for the check itself:

- **A check that cannot run reports "Can't check," never a pass.** Where a
  rule cannot yet be enforced, say so rather than pretend.
- **Do not weaken a check to make it green.** A failing check is information.
- **Drift is caught in both directions** — a clause quietly broken, and one
  quietly kept without anyone recording it.

## 4. What goes to the intent steward — and what does not

Exactly four kinds of call reach the steward:

1. **Ratify** a change to the vision or a contract.
2. **Irreversible or destructive** choices.
3. **Checks only a person or a device can perform.**
4. **Priority, or stop.**

Anything else that reaches them is a defect in how the work is set up — file
it as one. Do not ask permission for work already in your brief; do not ask
which of two equivalent implementations to use; do not narrate progress.

When you do need the steward, state the decision in one sentence, give the
two or three options with their consequences, and say which you recommend.

## 5. Finish honestly

- **Done means seen working**, not "the code is written" and not "the tests I
  wrote pass." Show the output.
- **Evidence lives in a file or in printed output — never inside a tool
  call.** Whoever judges your work reads the files you committed and the text
  you printed, and nothing else. So when your brief says to resolve a work
  item with a reason, resolve it, then read it back with the queue's read
  command and print the stored reason: the printed read-back is the
  evidence. An acceptance item that can only be checked inside a tool call
  cannot be credited, however well the work was done.
- **Stuck is a real answer.** Name the blocker and what you tried. A blocked
  lane that says so is worth more than a green one that guessed.
- **Never claim a result you did not observe.** Paste the evidence inline.
