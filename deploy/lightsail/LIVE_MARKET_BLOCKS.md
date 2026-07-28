# Live market blocks

Earnings profiles are operated in independent release-session blocks. A block
is a logical lifecycle and risk boundary; it does not require another copy of
the universal resolution worker.

The standard earnings sessions are:

- `PRE_MARKET`
- `POST_MARKET`

Every scheduled earnings profile must store both values below in
`resolution_profile_schedules.metadata`:

```json
{
  "live_block": "PRE_MARKET",
  "block_id": "2026-07-28-pre-market"
}
```

The canonical block ID is
`<US release date>-<lowercase session name>`. The date is the company's
announced US release date, not the local date of the deployment host.

## Lifecycle boundary

Only schedules in the selected block are changed together:

1. authenticate and pre-sign both outcomes;
2. verify the live resolution-worker heartbeat and aggregate block notional;
3. move the block's ready profiles to `ACTIVE`/`ENABLED`;
4. keep the other session `MANUAL`/`DISABLED`;
5. finish each resolved or missed profile independently;
6. disable every remaining profile when the block window closes.

Starting `PRE_MARKET` must not implicitly arm `POST_MARKET`. Starting
`POST_MARKET` requires a new guarded transition and a new production audit.
This keeps preparation capacity, notional accounting, incident handling, and
Telegram lifecycle messages attributable to one release session.

The SEC-API WebSocket remains connected continuously and may persist source
events for disabled profiles. Profile-driven HTTP/RSS polling runs only while
a corresponding execution profile is active. Persisting a source event does
not authorize trading: only an enabled profile in the selected block can
reach the strategy and executor.

## Completion

A source fact without an execution claim is a missed execution, not a reason
to replay an old fact after a profile is enabled. Close it explicitly:

- schedule: `MANUAL` plus terminal `EXPIRED`;
- execution profile: `DISABLED`;
- earnings rule: `DISABLED`;
- release catalog: `REPORTED`;
- retain source events and facts for audit.

An accepted order may remain live after the source event. Completing the
profile must not cancel that order unless a reviewed cancellation policy or
an explicit operator action requires it.

## Production checks

Before arming a block, verify:

- every member has a successful current authenticated preflight;
- no member already has a validated fact or execution claim unless it is an
  explicitly resumed incident;
- every profile belongs to the expected account and market;
- the worst-selected-outcome notional fits the reviewed block cap;
- the other earnings session remains disabled;
- the live worker has fresh supervision and trading heartbeats.

After activation, verify the exact enabled profile set, no unexpected claims,
fresh worker and scheduler heartbeats, and available PostgreSQL connections.

