# Replace-first and public polling production checkpoint

Date: 2026-07-27

## Reviewed release

- Replace-first implementation commit: `bcb1869`.
- Final public-feed hardening commit: `b56f979`.
- Final clean source archive SHA256:
  `bdef25d0408a7c2f37e72512474ac14c0f46b8e9b3c2a561ad7447d94e8351d6`.
- Image archive SHA256:
  `7815e87585fc5761903a8c8ee0d60be781d561c2682c7499395053a2057cfb9b`.
- Immutable image:
  `codexpoly@sha256:d603719cc477e2b0b9c6ed7c04ca8933bdb036ab43b9ffdf6c00024678f532fa`.

The clean Docker build independently passed the repository secret scan and
all `634` tests with one expected skip.

## Replace-first order supervision

The NVTS audit showed that the first tick-change handler sent cancellation,
then immediately required a terminal remote status. The CLOB still returned
`OPEN` during its eventual-consistency window, so the replacement at `0.999`
was never submitted even though the source order later became `CANCELLED`.

The corrected sequence is:

```text
exact owned-order inspection
    -> target-tick replacement placement
    -> exact best-effort cancellation request
    -> persistence
```

There is no post-cancel order read and no wait for a terminal cancellation
state. Replacement size uses the first inspected unfilled remainder. If a
cancellation fails after placement, the known replacement ID is persisted as
`UNKNOWN`; recovery cannot submit a blind duplicate.

Unit and lifecycle integration tests assert the exact
`inspect -> place -> cancel` operation order and exactly one remote
inspection.

## Public polling

Each active feed is now polled concurrently. One slow or failing IR endpoint
cannot delay its wire peer. Failure backoff is isolated per feed and grows
from one second to a bounded 30 seconds; a successful response resets only
that feed.

Known HTML character references in otherwise valid RSS are normalized without
allowing DTD or entity declarations. A valid `Content-Length` is read to its
exact bound, avoiding a wait for EOF when a CDN sends the complete body but
does not close the stream cleanly. Declared oversize, invalid length, and
incomplete bodies still fail closed.

The Navitas vanity RSS endpoint returned HTTP `520` intermittently. The
official GCS endpoint returned HTTP `200` and a body of `7886` bytes but did
not always close its stream correctly. A no-secret, no-database, non-trading
VPS replay with the final image successfully parsed:

```text
company_ir       7886 bytes   10 items   ok
globenewswire   32255 bytes   20 items   ok
```

The guarded GCS source-policy migration and read-only check passed in staging.
Production rejected the same migration without changing data because the
completed NVTS event is still inside its scheduled active window and the
profile is not yet `DISABLED`. The existing production feed therefore remains
on isolated backoff until the scheduler closes the NVTS window; the checked
migration can be applied afterward.

## Runtime promotion

Only these services were recreated on the final digest:

- staging `earnings-worker`;
- staging `resolution-worker` in shadow mode;
- production `earnings-worker`;
- production supervised live `resolution-worker`.

Production `notification-worker`, `profile-scheduler-worker`, and
`profile-readiness-worker` were not restarted.

Post-promotion evidence:

- staging SEC heartbeat: `connected=True`, `watches=19`, `errors=0`;
- staging resolution heartbeat: `mode=shadow`;
- production earnings SEC heartbeat: `connected=True`, `watches=19`;
- production resolution heartbeat: `mode=live`;
- the completed NVTS profile was attached without a new execution;
- the fresh fully-live runtime invariant passed;
- all 15 July 28 schedules remain armed as `AUTO_LIVE`.

No order was submitted during build, replay, migration, or deployment.
