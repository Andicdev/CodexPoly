# July 30 PRE_MARKET production audit

## Scope

The audited block contains VIRT, CI, YUM, ICE, and MA. Evidence came from:

- sanitized production worker logs;
- a read-only database transaction over source telemetry, claims, order
  groups, supervision events, and the resolution run journal;
- read-only authenticated remote-order inspection.

No order, schedule, profile, or trading configuration was changed by the
audit.

## Correctness and lifecycle

| Ticker | Value | Rule result | Schedule | Profile |
| --- | ---: | --- | --- | --- |
| VIRT | 1.82 | `1.82 > 1.82` is false, NO | COMPLETED | DISABLED |
| CI | 7.78 | `7.78 > 7.60`, YES | COMPLETED | DISABLED |
| YUM | 1.62 | `1.62 > 1.56`, YES | COMPLETED | DISABLED |
| ICE | 1.90 | `1.90 > 1.84`, YES | COMPLETED | DISABLED |
| MA | 5.04 | `5.04 > 4.77`, YES | COMPLETED | DISABLED |

All five parsers selected the intended metric and direction. Every schedule
completed independently and every profile detached without a lifecycle error.
VIRT was the only activation-window miss.

## Source latency

The run journal measures `filed_at` to parsed fact. It is not an estimate of
our document parser alone; almost all of it was spent waiting for the SEC
transport to expose the filing.

| Ticker | Winning discovery route | Filed to transport | Transport to fact | Total source latency |
| --- | --- | ---: | ---: | ---: |
| VIRT | SEC-API WebSocket | 20.016 s | 0.493 s | 20.505 s |
| CI | SEC-API WebSocket | 25.372 s | 0.343 s | 25.711 s |
| YUM | SEC-API WebSocket | 33.230 s | 0.481 s | 33.703 s |
| ICE | SEC-API WebSocket | 26.490 s | 0.219 s | 26.704 s |
| MA | SEC CIK submissions polling | 38.508 s | 0.309 s | 38.813 s |

MA's CIK-submissions poller beat the SEC-API WebSocket by about 3.3 seconds,
but it was still too late for a competitive fill.

The current `sec_current` route polls
`data.sec.gov/submissions/CIK##########.json`. It must not be described as the
SEC Latest Filings feed. SEC's own developer guidance says Latest Filings and
its RSS are the preferred resources for getting as close to real-time
availability as possible.

## Hot path after fact

| Ticker | Fact to claim | Exchange request | Outcome |
| --- | ---: | ---: | --- |
| CI | 28 ms | 60 ms | accepted open |
| YUM | 24 ms | 111 ms | accepted open |
| ICE | 68 ms | 46 ms | accepted open |
| MA | 43 ms | 394 ms | accepted open |
| VIRT | 1,451,908 ms | 44 ms | late replay after activation |

The normal parser/strategy/executor path is not the primary bottleneck. For
the four profiles that were live when their facts appeared, decision plus
exchange time was 88-437 ms.

## Orders and tick supervision

No matched quantity was recorded for any of the five runs. The journal
classified every run as `LATENCY_MISS`.

- CI submitted at effective `0.99`, detected the `0.001` tick, and opened the
  `0.999` replacement about 0.76 seconds later.
- YUM submitted at effective `0.99` and opened the `0.999` replacement about
  0.43 seconds later.
- ICE submitted at effective `0.99`; the `0.001` tick event was not observed
  until about 167.6 seconds later, then the `0.999` replacement was opened.
- MA submitted directly at `0.999`.
- VIRT replayed at `0.999`, more than 24 minutes after its fact.

The database retains `LIVE` replacement rows for CI, YUM, and ICE, consistent
with the reviewed policy that completing a profile does not cancel accepted
orders. Authenticated remote inspection returned a sanitized
`UnexpectedResponseError` for the inspectable CI and ICE order IDs, so remote
state could not be independently confirmed by this audit. No cancellation was
attempted.

## Public-source race

Public polling activated at 10:00 UTC for CI, YUM, and ICE and was configured
with three Business Wire watches. The feed was reachable, but produced no
tradable candidate for those companies. MA's Business Wire route also
produced no candidate.

Across the block:

- public poll cycles: 14,924;
- successful feed responses: 114;
- public candidates: 4, all related to VIRT;
- public trading signals: 0;
- observation-only public facts: 1.

The VIRT IR feed timed out 172 times and GlobeNewswire timed out once. These
routes ran in parallel and did not block SEC, but the error volume needs
per-feed circuit breaking and clearer readiness reporting.

The generic Business Wire earnings RSS must not count as an independent
production source until a replay or observation proves that the exact issuer
release appears within the required latency. Configuration presence is not
source readiness.

## Required changes

### P0 — before the next earnings block

1. Deploy timing-contract migrations 019/020 and the matching production
   image now that the July 30 block has ended.
2. Add a profile-gated SEC Latest Filings RSS/Atom discovery route, independent
   of both SEC-API WebSocket and CIK-submissions polling, within SEC's access
   policy.
3. Add issuer-specific direct listing/document probes for each earnings
   profile. A generic category RSS may remain a fallback but cannot satisfy
   the multi-source readiness gate.
4. Extend authenticated preflight so each advertised public route must pass a
   recent issuer-specific replay/probe. Otherwise mark it observation-only and
   show the profile as effectively `SEC_ONLY`.

### P1

1. Persist a source-race row even when a route returns no candidate, so the
   audit can distinguish `not published`, `feed omitted issuer`, `filter
   rejected`, and `transport failed`.
2. Add per-feed backoff/circuit-breaker health for repeatedly timing-out IR
   endpoints without slowing parallel routes.
3. Fix remote-order inspection for the sanitized
   `UnexpectedResponseError`, then reconcile remaining orders without
   changing the reviewed no-auto-cancel policy.
4. Compare ICE book snapshots with the tick event to determine whether the
   167.6-second delay was an actual exchange tick transition or a missed
   market-channel/book observation.

## What does not need redesign

- EPS parser correctness;
- strategy direction selection;
- prepared executor latency after fact;
- independent profile completion;
- submit-first replacement once a finer tick is observed.

The next latency work should focus on discovery before the fact reaches the
parser, not on shaving tens of milliseconds from the already-fast decision
path.
