# Resolution source and hot-path checklist

Use this checklist for every new event source, company, central bank,
regulatory filing, press release, market binding, or executor extension.
Passing the checklist is required before production activation.

## 1. Define the canonical event

- Assign one stable `source`, `scope_id`, subject, metric, and expected
  publication window.
- Record the exact market resolution wording and bind it to a deterministic
  strategy rule.
- Identify the authoritative issuer, fiscal period or decision date, units,
  accounting basis, and acceptable document types.
- Treat delivery providers as evidence channels for the same event, not as
  separate strategies.
- Preserve the winning public source URL in the canonical fact and Telegram
  notification.

## 2. Prove parser correctness

- Parse into a source-neutral fact before invoking strategy or execution.
- Validate issuer, period, metric label, units, value, and document identity.
- Prefer explicit labeled values. Positional or "last number" extraction is
  not sufficient without an independently validated structural anchor.
- Quarantine missing, duplicated, contradictory, stale, wrong-period, and
  unsupported values. Ambiguity must produce no `ResolutionSignal`.
- Test representative historical documents, the latest known shape,
  malformed documents, false-positive lookalikes, and both sides of every
  threshold.
- Keep parser fixtures and the parser version so the decision can be replayed
  after the event.

## 3. Race evidence routes independently

- Use multiple official routes when available: regulator stream, regulator
  HTTP endpoint, issuer IR, press-release wire, RSS, HTML, or PDF.
- Run independent routes concurrently. Never put a slower provider in front
  of a faster provider as a serial fallback.
- Keep at most one in-flight request per route and use bounded connect, read,
  and body-size limits.
- A slow, timed-out, or malformed route must not block rescheduling or result
  processing for another route.
- WebSocket connections may remain warm continuously. HTTP polling starts
  only while at least one reviewed profile is prepared and in-window.
- The first independently valid fact wins. Deduplicate later evidence by the
  canonical event identity and document fingerprint.
- Optimize format-specific parsing, such as checking the first PDF page
  before a bounded full-document fallback, without weakening validation.

## 4. Prepare everything before publication

Preparation must finish before source polling enters its hot window:

- load and validate all profiles and market bindings;
- resolve the trading account, wallet, signature type, condition, assets,
  outcome tokens, neg-risk parameters, tick size, minimum size, balance, and
  configured caps;
- refresh the necessary books and derive effective prices;
- build and locally sign both YES and NO alternatives;
- persist a stable `PreparationContext`;
- start required order supervision and market-channel watches;
- complete authenticated preflight and leave the profile disabled until its
  scheduled activation.

After the signal, account lookup, balance reads, book reads, market metadata,
database discovery, client construction, and signing are prohibited.

## 5. Batch one publication as one execution

- One canonical publication produces one `ResolutionSignal`.
- Evaluate all strategies for that signal together.
- Select all applicable `OrderIntent` objects before calling the executor.
- Call one shared `PreparedExecutor` once for the complete selected set.
- Use one exchange batch submission for all selected orders when the exchange
  supports it.
- Do not construct one client or executor per market profile.
- Opposing YES/NO alternatives share a selection group for preparation risk;
  only the maximum selectable alternative contributes to worst-selected
  notional.
- If more than one intent is selected from the same exclusive selection
  group, fail the complete batch before creating a claim or submitting any
  order.

## 6. Keep the post-signal path minimal

The synchronous hot path is:

```text
official bytes
    -> bounded parser
    -> canonical ResolutionSignal
    -> deterministic strategy selection
    -> persistent idempotency reservation
    -> one exchange batch submission
```

Telegram, source summaries, enrichment, analytics, and nonessential journal
updates occur only after submission or through an asynchronous outbox.
Necessary persistence must be bounded and must not re-read configuration.

Tick-size repricing is a separate supervised lifecycle. When the configured
risk policy permits it, submit the already prepared finer-tick replacement
before best-effort cancellation so cancellation consistency cannot block the
replacement.

## 7. Measure every boundary

Use monotonic clocks for durations and UTC clocks for cross-service event
correlation. At minimum record:

- route request start, response status, byte count, fetch duration, parse
  duration, and winning provider;
- canonical fact and signal creation time;
- strategy completion and selected intent count;
- idempotency reservation start and completion;
- exchange submission start, acknowledgement, and returned order IDs;
- post-submission supervision and replacement timing.

Telemetry must contain safe identifiers and error types, never secret values
or unsanitized exception text. Report p50, p95, maximum, and per-stage totals
when enough events exist. An aggregate "signal took N seconds" is not an
adequate latency diagnosis.

## 8. Required tests before activation

- Historical parser replay accepts every supported shape.
- Negative fixtures fail closed and cannot create an intent.
- A delayed route cannot block a faster route.
- Repeated unpublished responses followed by a release are detected.
- Both outcomes and all market templates prepare before the signal.
- A hot-path test makes account, balance, book, metadata, and signing methods
  raise after preparation; execution must still succeed.
- One multi-market signal causes one executor call and one exchange batch
  call.
- Duplicate selection groups and malformed batch responses fail before blind
  retries.
- Restart and duplicate-worker tests prove persistent idempotency.
- Secret scan and the complete repository test suite are run before commit.

## 9. Production activation gate

- Store the reviewed parser version, source routes, market bindings, schedule,
  caps, and profile template in version control or additive database rows.
- Record the earliest possible tradable signal separately from any webcast
  or conference call. `activate_at` must precede `earliest_signal_at` by the
  reviewed safety lead; an unknown exact publication time requires a
  conservative session floor or prior-quarter minimum, never the call time.
- Research the issuer's news/release-details announcement in addition to its
  event-calendar card. Treat an event-card timestamp as a call/webcast unless
  issuer text explicitly says the financial materials are published then.
- Treat `at HH:MM` as an exact publication time only when the issuer attaches
  it to `release`, `publish`, `post`, or equivalent language. Treat
  `no later than HH:MM` as a latest-publication deadline, never as
  `earliest_signal_at`; use a conservative session floor instead.
- Persist separate evidence for publication and call times. A single event
  page or one timestamp copied into both fields fails timing review.
- Require `timing_contract_version=1` before an `AUTO_LIVE` transition.
- Run authenticated preflight without submitting orders.
- Confirm preparation freshness, runtime heartbeat, route telemetry, and
  supervision readiness.
- Activate only the intended event block; unrelated profiles remain disabled.
- After the event, record direction correctness, source winner, stage
  latencies, exchange result, fill quality, resting price, and every error in
  the run journal.
- Treat each live event as evidence for the next iteration: preserve working
  paths, fix measured bottlenecks, and never infer speed from market outcome
  alone.
