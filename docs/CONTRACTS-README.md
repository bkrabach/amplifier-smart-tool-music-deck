# The contracts

A **contract** is a short promise this project must keep — written for
people, precise enough to check against reality. The **vision**
(`docs/VISION.md`) says where the project is going; the contracts say what
must be true along the way. Together they are the through-line: the same text
a colleague reads is the text every AI session obeys.

## The index

| Contract | What it promises | Who builds against it |
|---|---|---|
| [`contracts/cli.v1.md`](../contracts/cli.v1.md) | The stable `music-deck` invocation surface: verbs, exit codes, output shape, the frozen refusal vocabulary. | This repo's CLI; any agent or script invoking `music-deck`. |
| [`contracts/boundary.v1.md`](../contracts/boundary.v1.md) | The Spotify/model boundary, PKCE auth, disconnect, and managed-conversation retention limits. | The owner running music-deck under their own Spotify app; the library's model/HTTP/filesystem layers. |
| [`contracts/plan.v1.md`](../contracts/plan.v1.md) | The shape of a plan document: required fields, step shape, strict validation, how `apply` executes it. | `music-deck plan` (producer), `music-deck apply` (consumer), anyone who hand-edits a plan. |
| [`contracts/refusals.v1.md`](../contracts/refusals.v1.md) | The closed public error vocabulary and error-envelope behavior. | The CLI, library error boundary, and callers handling failures. |
| [`contracts/do.v1.md`](../contracts/do.v1.md) | Bounded model-backed music operations, observed outcomes, explicit continuation, and managed-history limits. | `music-deck do`, its native agent and library adapters, callers continuing work, and reviewers of account effects. |

## The anatomy every contract follows

One file, one contract, about one screen — fifty to a hundred lines. Same
sections, same order, every time (`contracts/documents.v1.md` in the upstream
Converge bundle is the authority for this shape):

1. **H1 with the status in parentheses** — `(DRAFT)` while it is a draft, and
   the locked stamp with its date once the steward has locked it. Status
   lives here and nowhere else.
2. **Line 3: `**Who builds against this:**`** — the people and systems that
   would be surprised by a silent change.
3. **Purpose** — why this contract exists, in a short paragraph.
4. **Core (the teeth)** — numbered clauses. Each leads with the rule as a
   fact, in bold, then one to three plain lines of why.
5. **What v1 deliberately does NOT freeze** — each with the trigger that
   would promote it into the teeth.
6. **Conformance kit asserts** — what a machine, or a named reader, checks.
7. **Reserved / open questions** — explicitly not law.
8. **Changelog** — present only once the contract has been amended.

Written for amplified information workers: anyone who has never opened a code
editor can read it and know what it means. Technical detail is folded into a
marked section, never carried in the deciding sentence.

## When a contract locks

A contract is **draft** until all four are true — then, and only then, the
intent steward locks it and others are turned loose against it:

1. It says what it means.
2. It carries a real example of right and wrong.
3. It can be checked against reality.
4. The steward has read it and agreed.

A locked contract carries the locked stamp and its date in the H1. Nothing
edits one in place — not a person, not an AI session. The repository refuses
(see `PINS.md`).

## How to propose a change

Write a sibling file named `<contract>.vN-candidate.md` — for example
`contracts/cli.v2-candidate.md`. It has three parts, in order:

1. **The exact change**, sentence by sentence, shown as a fenced before/after
   pair: the current text in one fenced block, the replacement in a second.
2. **The evidence** — a cost actually paid or a failure actually caught.
   Preference is not evidence.
3. **What does *not* change.**

The original stays the law until the steward answers with one word:
*ratified* · *ratified with edits* · *declined* · *later*.

## The two guards

- **Pre-push scan** (`.githooks/pre-push`) — refuses a push that edits a
  locked contract without a `*-candidate.md` sibling in the same push.
  Enable once per clone: `git config core.hooksPath .githooks`.
- **Upstream Smart Tools kit** — `music-deck` conforms to
  `microsoft/amplifier-smart-tools` @ `fd3c634`; a green run of its
  conformance kit against this repo root is a merge gate.
