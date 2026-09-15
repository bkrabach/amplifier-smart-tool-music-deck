target: contracts/do.v1.md
cross-file target: contracts/boundary.v1.md

# Exact change

## Change 1 — `do.v1` Core 4, transcript scope

Current text:

```
Every prompt actually
   sent or replayed in the current turn is observable in its transcript.
```

Replacement:

```
The observable, application-owned transcript records exactly the caller brief,
   caller context, application instructions, and music-tool projections
   music-deck supplied to the public engine binding. It may include selected
   prior application history only when that history is explicitly labelled. It
   does not claim to reconstruct a complete engine-assembled prompt or provider
   wire payload.
```

## Change 2 — `do.v1` conformance kit, transcript evidence

Current text:

```
- Offline fixtures cover crash uncertainty, full current-turn transcript, no
  historical mutation replay, `0700` directory and `0600` file/sidecar modes,
  lease-safe purge, and one-call `--local` observation. Model and storage spies
  prove injected credentials are rejected before either receives them.
```

Replacement:

```
- Offline fixtures cover crash uncertainty; an application-owned transcript
  that exactly records the caller brief, caller context, application
  instructions, and music-tool projections supplied to the public engine
  binding; explicitly labelled selected prior application history; no
  historical mutation replay; `0700` directory and `0600` file/sidecar modes;
  lease-safe purge; and one-call `--local` observation. Model and storage spies
  prove injected credentials are rejected before either receives them.
```

## Change 3 — `boundary.v1` Core 3, observable output

Current text:

```
3. **The prompt transcript is an observable output.** The result document
   carries `transcript` — every prompt sent, verbatim — so a reviewer sees what
   crossed without reading code. Clause 1 makes this load-bearing.
```

Replacement:

```
3. **The application-owned transcript is an observable output.** The result
   document carries `transcript`: exactly the caller brief, caller context,
   application instructions, and music-tool projections music-deck supplied to
   the public engine binding, with selected prior application history explicitly
   labelled. It lets a reviewer see what music-deck supplied without reading
   code; it neither attests nor reconstructs engine-assembled prompt material,
   adapter/provider transformations, or a provider wire payload. Clause 1 makes
   this bounded output load-bearing.
```

## Change 4 — `boundary.v1` conformance kit, transcript evidence

Current text:

```
- Every prompt and projected tool result the substrate captured appears verbatim
  in the observable output: what crossed is what the caller can read back.
```

Replacement:

```
- A recording public-binding substitute captures the caller brief, caller
  context, application instructions, and music-tool projections supplied by
  music-deck; each captured application input appears verbatim in the observable
  output. Selected prior application history is present only when explicitly
  labelled. A test adapter that adds or transforms internal/provider input must
  not cause the transcript to manufacture or claim that material.
```

# Evidence

Evidence recorded: 2026-09-15 UTC.

The existing promise is concretely unmeetable through the current public
interface, not merely inconvenient. At `microsoft/amplifier-agent` v1 commit
`412cc176cfa5bd219254060ede7f03bbf6578005`, the agent interface accepts the application
input but exposes no public, attested observer of the complete assembled request
or provider wire payload. Its traced adapter path transforms input into
`provider_input` after the public binding. Therefore `do.v1` Core 4's exact
promise (``Every prompt actually sent or replayed in the current turn is
observable in its transcript.``) and `boundary.v1` Core 3's ``every prompt sent,
verbatim`` cannot be truthfully proven by music-deck without reconstructing or
inventing internal data.

Source: that revision's `contracts/agent-interface.v1.md:75-94` lists the closed
options, and `:360-373` explicitly excludes prompt assembly. The reviewed
implementation converts provider input after application submission in
`packages/engine/src/amplifier_agent_engine/_engine/provider_inputs.py:36-53`.
These are source-inspection findings, not a claim of a new runtime experiment.

Falsifiers for the replacement are deliberately narrow:

- A recording public binding receives the application inputs and the emitted
  transcript differs by any byte, omits a supplied field, or includes selected
  history without its label.
- A credential-bearing brief, context, instruction, tool projection, or selected
  history reaches either the public binding or a persistence sink; rejection must
  occur before both sinks.
- An adapter/provider fixture contributes an internal instruction or transformed
  `provider_input` and the transcript presents it as captured application input,
  or tries to reconstruct it.

The honest trade-off is less observability than originally requested: reviewers
can verify exactly what music-deck supplied at its public boundary, not every
internal engine or provider payload. This does not weaken security; it keeps the
pre-content credential-admission requirement intact. Host/public pre-content
admission still requires an upstream solution. This document alone does not
unblock safe continuation.

# What does NOT change

- Credentials, provider keys, and raw tokens remain prohibited from prompts,
  native history, output, and managed persistence; credential-bearing material
  remains rejected before model delivery or any history/checkpoint persistence.
- Explicit saved-session creation and resume, account/application binding,
  single-writer leases, monotonic restrictive policy, unknown-write fail-closed
  behavior, retention location and permissions, deletion, and disconnect cleanup
  remain unchanged.
- The music-domain authority boundary, no operational escape hatch, outcome
  reporting, caller budgets, local-observation limits, and privacy protections
  remain unchanged. This proposal does not authorize provider-payload capture or
  retention.
- The steward, not this proposal, decides whether the reduced observability is
  acceptable.

# Steward decision

Decision: **Ratified — 2026-09-15.** The steward answered “ratified” to the two
product amendments. This includes the explicit `boundary.v1` targets above,
not the separate upstream content-admission candidate. It records direction,
not a freeze or an implementation pass.
