# Earnings source-tail production deployment — 2026-07-30

## Immutable boundary

- Source commit: `d1c73de`
- Source archive SHA256:
  `2cd0d3d26d4c4c05aef7bd842b40970fba5c1938689bc8b286c09324115ca9c9`
- Image:
  `codexpoly@sha256:01bf58c785d42b2dcb3f0d5eae5da7fe693473a28615f20595e85059194475d0`
- Image archive SHA256:
  `5785e6cf662c910bb9fa94a20e29ea0619c8b7be21dd01e107959a94cab73923`
- Build label: `org.opencontainers.image.revision=d1c73de`

The image was built from `git archive`, not from the working tree. The
Docker build repeated the repository secret scan and all 813 tests.

## Staging

Migration 018 and its guarded schema verifier completed successfully. Only
the base shadow `earnings-worker` and `resolution-worker` were recreated.
The resulting heartbeat confirmed:

- SEC-API WebSocket connected with 34 watches and zero errors;
- no active or observation-tail scope;
- no source signals or observed facts;
- no resolution profile.

The exact tested image archive was then loaded into the production Docker
daemon.

## Production

Migration 018 completed before the worker restart. Guarded checks confirmed
that every July 29 post-market profile was disabled, HOOD was terminal, and
the MSFT parser quarantine was closed. Name-only secret checks passed for the
earnings, trading-resolution, and notification services.

The five production workers were recreated with the existing live guards and
caps:

```text
CBR_LIVE_MAX_ORDER_QTY=100
CBR_LIVE_MAX_NOTIONAL=100
CBR_LIVE_MAX_TOTAL_NOTIONAL=1000
PROFILE_SCHEDULER_MAX_TOTAL_NOTIONAL=1000
```

All five workers now run the immutable digest above with restart count zero.
The final sanitized heartbeats showed:

- SEC WebSocket connected with 20 watches and zero errors;
- public and SEC-current polling inactive with zero active/tail scopes;
- live resolution healthy with zero profiles;
- scheduler `auto_live=True`, with no requested or activated schedule;
- readiness checked zero profiles;
- notification delivery had zero failures.

No execution profile was enabled and no trading action was created by this
deployment.

## Scheduler correction

The first manual Compose recreation omitted the separate non-secret
`PROFILE_SCHEDULER_MAX_TOTAL_NOTIONAL` value. The scheduler failed closed
before running and the discarded container restarted nine times. Sanitized
logs identified the missing setting. It was immediately recreated with cap
`1000`; the replacement container reported `ready`, restart count zero, and
no requested or activated schedule.

The new scheduler also treats `BLOCKED` as terminal. After it was healthy,
guarded migration 034 restored the EA schedule from the old scheduler's
incorrect `EXPIRED` state to the operator-selected `BLOCKED` state with
reason `official_schedule_unconfirmed`. The exact EA terminal guard and the
all-disabled guard both passed.

## Observation-only source race

After an earnings schedule transitions from `ACTIVE` to `COMPLETED`,
`BLOCKED`, or `EXPIRED`, public and SEC-current polling continue for 900
seconds. The tail is reconstructed from append-only lifecycle events, so a
worker restart does not silently end it.

Tail candidates are fetched and parsed but persisted with status `OBSERVED`.
The processor returns before validated-fact loading, `ResolutionSignal`,
strategy, executor, and Telegram. The tail therefore measures late sources
without creating a second trading path.

Use `earnings_source_race_observations` after the next real event. Its useful
timestamps are:

- `provider_published_at`: timestamp declared by the provider;
- `transport_observed_at`: first time CodexPoly saw the publication on that
  transport;
- `document_fetch_started_at` and `document_fetch_completed_at`;
- `parse_completed_at` and `fact_persisted_at`;
- `source_race_rank` and `source_race_lag_ms`;
- `agrees_with_winner`, which catches a fast but semantically wrong parser.

The key latency comparison is based on `transport_observed_at`, not merely
the provider-declared publication time. At deployment there was no in-window
profile, so the correct initial state was `tail_scopes=0`; the first real
post-terminal tail will populate the additional source observations.
