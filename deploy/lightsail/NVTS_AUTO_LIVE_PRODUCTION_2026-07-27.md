# NVTS AUTO_LIVE production checkpoint

Date: 2026-07-27

## Approved scope

The separately reviewed `earnings-nvts-2026q2` profile was approved for
automatic production activation with:

- source scope `earnings:NVTS:2026Q2`;
- preflight at `2026-07-27 18:45 UTC`;
- execution window from `2026-07-27 19:00 UTC` through
  `2026-07-28 03:00 UTC`;
- maximum quantity `50`;
- maximum per-order notional `50`;
- maximum aggregate reviewed notional `1000`.

The profile retains the shared order template: both outcomes request price
`0.999` and quantity `50`. The prepared executor applies the live market tick
before submitting an order.

## Database promotion

Production was backed up immediately before the change.

Seed `011_schedule_nvts_auto_live.sql` completed atomically in production.
The fail-closed verification in `verify_nvts_auto_live_armed.sql` then
confirmed:

- the schedule is `AUTO_LIVE / PENDING`;
- the execution profile remains `DISABLED` before preflight;
- no validated fact, execution claim, or active order group exists for this
  scope;
- the live resolution heartbeat is fresh;
- the reviewed worst-selected-outcome notional across all 16 AUTO_LIVE
  schedules is `799.2`, below the `1000` cap.

The same seed was intentionally not forced through staging. Staging does not
run a live trading heartbeat, so its production-only heartbeat predicate
failed closed and the transaction made no change.

## Runtime state

At `2026-07-27 17:30 UTC`, all five production workers were up on immutable
image `codexpoly@sha256:126542b82129ee691c61217edbc7f2df9148e469603977ebdccefa77a68751c0`.

Sanitized scheduler health showed `auto_live=True` with no requested,
activated, blocked, or expired transitions. This is the expected state before
the `18:45 UTC` preflight.

The scheduler is responsible for requesting authenticated preflight and then
enabling the profile at the execution-window boundary only if readiness still
passes. The scheduler has no trading-key secret mount. Order preparation and
submission remain confined to the supervised live resolution worker.

No order was prepared or submitted while this schedule was added.
