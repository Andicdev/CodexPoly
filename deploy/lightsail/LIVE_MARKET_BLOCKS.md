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

## Earliest-signal timing contract

Conference-call and webcast times are not release times. An earnings release
may appear on the issuer site, a press wire, or SEC before the call. Every new
schedule therefore stores a versioned timing contract in first-class columns:

- `earliest_signal_at`: conservative floor for any tradable publication;
- `activation_safety_lead_seconds`: required live lead before that floor;
- `timing_basis`: `OFFICIAL_EXACT`, `OFFICIAL_WINDOW`,
  `HISTORICAL_PATTERN`, or `SESSION_FLOOR`;
- `timing_source_url`: reviewed HTTPS evidence;
- `timing_contract_version=1`.

The invariant is:

```text
activate_at <= earliest_signal_at - activation_safety_lead
preflight_at < activate_at
conference_call_at is informational only
```

If the issuer confirms only a call, use a conservative session floor or the
earliest observed publication across prior quarters. Never derive
`activate_at` by subtracting an arbitrary offset from the call. New
`AUTO_LIVE` inserts, transitions, and activation-time changes fail closed in
PostgreSQL without a valid versioned contract. Existing version-0 schedules
remain readable for backward compatibility.

## Lifecycle boundary

Only schedules in the selected block are changed together:

1. authenticate and pre-sign both outcomes;
2. verify the live resolution-worker heartbeat and aggregate block notional;
3. move the block's ready profiles to `ACTIVE`/`ENABLED`;
4. keep the other session `MANUAL`/`DISABLED`;
5. finish each resolved or missed profile independently;
6. disable every remaining profile when the block window closes.

Authenticated preflight is retryable while the schedule remains
`PREFLIGHTING`. A transient failed attempt records a classified safe error and
sets a short retry lease; it does not immediately make the profile
`BLOCKED`. The scheduler still fails closed at the activation-grace deadline
if no attempt reaches `READY`.

Starting `PRE_MARKET` must not implicitly arm `POST_MARKET`. Starting
`POST_MARKET` requires a new guarded transition and a new production audit.
This keeps preparation capacity, notional accounting, incident handling, and
Telegram lifecycle messages attributable to one release session.

The SEC-API WebSocket remains connected continuously and may persist source
events for disabled profiles. Profile-driven HTTP/RSS polling runs only while
a corresponding execution profile is active, followed by a bounded
observation-only tail. Tail facts use `OBSERVED`, not `VALIDATED`, and cannot
reach the source, strategy, executor, or Telegram. Persisting a source event
does not authorize trading: only an enabled profile in the selected block and
a `VALIDATED` fact can reach the strategy and executor.

## Completion

A source fact without an execution claim is a missed execution, not a reason
to replay an old fact after a profile is enabled. Close it explicitly:

- successful strategy/executor path: schedule `COMPLETED`;
- terminal source-contract, strategy, preparation, or execution error:
  schedule `BLOCKED` with its safe reason;
- unresolved window: schedule `EXPIRED`;
- execution profile: `DISABLED`;
- retain source events and facts for audit.

`BLOCKED` is a terminal operator-visible state. Window expiry must not replace
it with `EXPIRED` or clear its reason.

The runtime completes each profile independently immediately after its
coordinator consumes the signal. Historical operator-run completions that used
`MANUAL` plus `EXPIRED` remain valid and require no rewrite. Earnings rule and
catalog status are source-side audit concerns and no longer determine whether
the profile can trade.

An accepted order may remain live after the source event. Completing the
profile must not cancel that order unless a reviewed cancellation policy or
an explicit operator action requires it.

## Production checks

Before arming a block, verify:

- every member has a version-1 earliest-signal timing contract;
- activation precedes the earliest signal by the reviewed safety lead;
- release evidence is distinct from call/webcast evidence;
- every member has a successful current authenticated preflight;
- no member already has a validated fact or execution claim unless it is an
  explicitly resumed incident;
- every profile belongs to the expected account and market;
- the worst-selected-outcome notional fits the reviewed block cap;
- the other earnings session remains disabled;
- the live worker has fresh supervision and trading heartbeats.

After activation, verify the exact enabled profile set, no unexpected claims,
fresh worker and scheduler heartbeats, and available PostgreSQL connections.
