# July 2026 FOMC production live checkpoint

Date: 2026-07-29

## Approved risk boundary

The operator explicitly approved a one-time restart inside the normal
15-minute worker restart exclusion window and accepted:

- five FOMC markets;
- quantity `5000` on each selected outcome;
- maximum order quantity `5000`;
- maximum per-order notional `5000`;
- maximum aggregate prepared notional `26000`;
- reviewed FED worst-selected-outcome notional `24975`.

All five profiles remained disabled until a fresh authenticated preflight
completed with the increased limits.

## Activation

The immutable production image was:

```text
codexpoly@sha256:4ef4fbbdea1867e39beddaee7828f986f86ba0b2d44130b05e5dc0b423a6c747
```

`resolution-worker`, `profile-readiness-worker`, and
`profile-scheduler-worker` were recreated with effective limits
`5000 / 5000 / 26000`. The live worker heartbeat then confirmed live mode,
supervision, and trading.

The old readiness worker briefly evaluated the new quantities against its
old `100 / 100 / 1000` limits. Migration
`028_retry_fed_july_preflight_after_caps.sql` retried only the five expected
cap-related failures after the new limits were effective. All five
authenticated preflights then passed. Migration
`029_arm_fed_july_quantity_5000.sql` changed only those schedules to
`AUTO_LIVE`; scheduler activation produced five `ACTIVE / ENABLED` profiles.

The FED worker attached:

```text
profiles=5 templates=10 states={'READY': 5}
```

No source or preparation error was present before publication.

## Event and execution

The Federal Reserve Board statement was accepted at:

```text
2026-07-29T18:00:03.521Z
```

The parsed target range was unchanged at `3.50%-3.75%`. The five selected
outcomes were:

- YES on no change;
- NO on increase 25;
- NO on increase 50 or more;
- NO on decrease 25;
- NO on decrease 50 or more.

All five execution claims were successfully submitted between
`18:00:03.626Z` and `18:00:05.225Z`. Read-only remote-order inspection later
showed:

- no change: `5000 / 5000` filled;
- increase 25: `5000 / 5000` filled;
- increase 50 or more: `5000 / 5000` filled;
- decrease 25: `5000 / 5000` filled;
- decrease 50 or more: `0 / 5000` filled and still live at `0.999` as of
  `18:09:11Z`.

The last order was not cancelled or modified. It remains owned by the
supervision path. All five schedules completed and all five execution
profiles returned to `DISABLED`.

## Verified invariants

The production migration runner confirmed, without returning confidential
data:

- exactly five successful selected-outcome FED claims;
- no pending or failed FED execution claim;
- correct YES/NO outcome mapping;
- all five lifecycle schedules `COMPLETED`;
- all five profiles `DISABLED`;
- a fresh supervised live resolution heartbeat.

The global workers still carry the temporarily approved elevated limits.
They must be returned to `100 / 100 / 1000` after the active July 29
POST_MARKET earnings block is terminal; restarting the resolution worker
while that block is active remains unsafe.
