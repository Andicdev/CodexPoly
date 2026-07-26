# SEC filing shadow source

The hosted worker now shares one source-neutral SEC transport:

```text
SEC-API WebSocket
    -> SecFilingEnvelope
    -> EarningsRouter -> EarningsDocumentCandidate -> company parser
    -> MstrBtcRouter -> MstrBtcDocumentCandidate -> holdings-first parser
```

There is still exactly one WebSocket connection. Transport decoding knows
nothing about earnings or MSTR semantics; each router independently applies
its issuer, form, document, and event-window rules.

The MSTR branch is shadow-only. It selects the primary initial `8-K`, pins the
validated holdings state that existed before the weekly window, downloads the
document through the same bounded SEC/SEC-API fetcher, and runs the
holdings-first parser. Unrelated MSTR `8-K` filings return `NO_MATCH`.

Migration 009 stores the routed event, canonical weekly fact, and processing
results in three database-enforced append-only tables. A temporary `ERROR` can
be retried; `ACCEPTED`, `NO_MATCH`, and `QUARANTINED` are terminal and
idempotent. An accepted canonical fact fans out into the three current
market-scoped shadow signals:

- acquired BTC `> 0`;
- acquired BTC `> 1000`;
- sold BTC `> 0`.

The strict 1000-BTC branch requires an explicit acquisition value when a
holdings-derived quantity is within one BTC of the boundary. The other branch
of a one-sided filing may resolve to zero only when the holdings equation
cross-checks within the parser's one-BTC tolerance.

These MSTR signals are persisted only as source facts and logged in the source
worker. The branch does not yet update canonical holdings state, configure a
resolution execution profile, call a strategy, create an `OrderIntent`, or
reach an executor.

The source service deliberately has no dependency on a strategy,
`OrderIntent`, or `PreparedExecutor`. An earnings signal emitted here cannot
place an order unless a separate later composition explicitly wires it to
those layers.

The separate hosted composition lives in
`cbr_trading.resolution_hosted`. It reads only persisted `VALIDATED` facts,
builds `ResolutionSignal -> NumericThresholdStrategy -> OrderIntent`, and
passes the selected intent to the source-neutral executor. The SEC source
service still has no trading dependency or signing secret.

## Checked-in company rules

The checked-in rules remain `SHADOW` configurations:

- NVTS fiscal 2026 Q2: non-GAAP EPS `> -0.04`, expected July 27;
- WWD fiscal 2026 Q3: GAAP diluted EPS `> 2.42`, officially scheduled for
  July 29 at approximately 16:00 ET;
- BBBY fiscal 2026 Q2: non-GAAP diluted EPS `> -0.26`, officially scheduled
  for August 4 after market close.

The WWD and BBBY Polymarket slugs retain the platform's original July 27
estimated date. Their official investor-relations announcements supersede that
estimate for monitoring time; the market rule itself continues to refer to the
next quarterly release.

The SEC router accepts only an initial `8-K` with `Item 2.02` and one
`EX-99.1` press-release exhibit for the watched ticker/CIK. It rejects
amendments, unrelated filings, ambiguous exhibits, and identity mismatches.

The Navitas parser requires the expected fiscal period and the exact
reconciliation row for non-GAAP net loss per share. Missing non-GAAP EPS
returns `NO_MATCH`; it never produces a premature `NO` resolution.

The Woodward parser requires the expected fiscal period, the explicit
fully-diluted basis statement, and the headline as-reported GAAP
`Earnings per share (EPS)` row. It does not substitute adjusted EPS.

The Bed Bath & Beyond parser requires the expected fiscal period and the
current-period reconciliation from diluted GAAP loss per share to
`Adjusted Diluted EPS`. It does not substitute the GAAP loss or a prior-period
column.

## Explicit database setup

Normal runners never apply migration 004. Check readiness with:

```text
python -m scripts.manage_earnings_schema
```

Explicitly create the three additive tables and save every checked-in shadow
rule:

```text
python -m scripts.manage_earnings_schema --apply --seed-checked-in-shadow
```

The legacy `--seed-nvts-shadow` option remains available. Both seed modes keep
rules in `SHADOW` and do not create source events, fact candidates, execution
claims, or orders.

## Hosted shadow worker

Run the long-lived source worker with:

```text
python -u -m cbr_trading.earnings
```

Before opening the WebSocket, run the presence/schema/rule preflight:

```text
python -m scripts.check_earnings_shadow_runtime
```

It reports only the selected database target, credential presence, active
scope names, watch count, and missing parser names.

It performs this loop:

1. verifies migration 004 and, when MSTR shadow is enabled, migrations 008
   and 009, without applying migrations;
2. loads only `SHADOW` and `WATCHING` rules;
3. opens one source-neutral SEC WebSocket connection;
4. fans normalized envelopes out to the earnings and MSTR routers;
5. downloads only a bounded public `https://*.sec.gov` document;
6. runs the selected semantic parser;
7. for earnings, persists a validated fact and logs a shadow
   `ResolutionSignal`;
8. for MSTR, persists the append-only source audit and logs only aggregate
   signal values against the pinned baseline.

The worker rejects any mode except `shadow`. It does not import a strategy,
account repository, Polymarket client, `OrderIntent`, or `PreparedExecutor`.
Rule changes are picked up on the next reconnect or service restart.

Required confidential runtime values:

- a configured primary database URL;
- one of `SEC_API_KEY`, `SEC_API_IO_KEY`, or `SEC_API_STREAM_KEY`.

Keep both in a restricted platform Secret Group. Do not attach trading-account
or Polymarket signing secrets to the shadow source service.

`MSTR_BTC_SHADOW_ENABLED=true` is an explicit non-secret deployment switch.
The checked-in Jul 21–27 watch is time-bounded and cannot route a filing
outside that interval.

`MSTR_BTC_LEDGER_ENABLED=true` starts the independent Strategy Ledger poller
inside the same non-trading source service. It requires MSTR shadow to be
enabled. `MSTR_BTC_LEDGER_POLL_SEC` defaults to `2` and
`MSTR_BTC_LEDGER_TIMEOUT_SEC` defaults to `10`. The poller uses conditional
requests and stores an audit event only after a new, contiguous,
holdings-reconciled Ledger row appears.

## Historical replay

Run the parser against four official Navitas IR releases without storing the
documents:

```text
python -m scripts.replay_navitas_earnings
```

## End-to-end synthetic resolution

Before the real release, inject a normalized EPS fact after the parser and run
the real source, numeric threshold strategy, and authenticated executor
preflight:

```text
python -m cbr_trading.simulations.earnings_resolution --eps -0.03
python -m cbr_trading.simulations.earnings_resolution --eps -0.04
```

For the NVTS rule these cases must select `YES` and `NO`, respectively. The
simulator prepares and pre-signs both market outcomes, then returns one
`DRY_RUN` result for the selected outcome. It never submits an order.

The injected fact is kept only in memory: no source event or fact candidate is
stored. Every run also uses a unique synthetic signal scope, leaving the real
`earnings:NVTS:2026Q2` idempotency scope untouched for Monday.

## Hosted resolution orchestrator

Migration 005 adds only `resolution_execution_profiles`. Each row contains
the pre-publication scope, Polymarket condition, account, separate YES/NO
prices, quantity, lifecycle policy, and a mandatory preparation/expiry
window. New and updated profiles remain `DISABLED`; an enabled profile outside
its time window is not loaded.

Apply migrations 005 and 006 explicitly:

```text
python -m scripts.manage_resolution_profiles --apply
```

Migration 006 adds `resolution_profile_templates` and seeds the operator
template `default` with YES/NO desired price `0.999`, quantity `50`, and the
`0.01 -> 0.001` repricing policy. Reapplying the migration never overwrites
an operator-edited template. Existing execution profiles also remain
unchanged when the template is edited.

Inspect or update the non-secret default through the management command:

```text
python -m scripts.manage_resolution_profiles \
  --show-template default

python -m scripts.manage_resolution_profiles \
  --set-template default \
  --yes-price 0.999 \
  --no-price 0.999 \
  --quantity 50
```

Configure each earnings market with its account and time window.
Prices, quantity, and lifecycle are copied from `default` unless an explicit
per-profile override is supplied. Configuration does not enable the profile:

```text
python -m scripts.manage_resolution_profiles \
  --configure-earnings NVTS \
  --account-name <account> \
  --prepare-from <UTC-ISO-8601> \
  --expires-at <UTC-ISO-8601>
```

Repeat for `WWD` and `BBBY`. Enable each profile only after its authenticated
preflight:

```text
python -m scripts.manage_resolution_profiles \
  --enable-profile earnings-nvts-2026q2
```

Run the separate service with:

```text
python -u -m cbr_trading.resolution_hosted
```

`RESOLUTION_ORCHESTRATOR_MODE=shadow` is the default and uses a non-submitting
executor. `preflight` authenticates, checks both market outcomes, verifies
collateral and caps, and pre-signs without submitting. `live` uses persistent
resolution claims and requires tick supervision for every
`reprice_on_tick_change` profile. A profile condition ID must exactly match
the active source rule before either outcome is prepared.

A controlled live smoke additionally requires every explicit guard, an armed
live environment, and post-only safety:

```text
python -m cbr_trading.simulations.earnings_resolution \
  --eps=-0.03 \
  --quantity 5 \
  --limit-price 0.10 \
  --run-id <unique-run-id> \
  --live-test \
  --expected-outcome YES \
  --confirm-live-order \
  --cancel-after-test
```

It submits only the selected outcome and immediately inspects and cancels only
the exact returned order ID. The command succeeds only after terminal cleanup
is confirmed and recorded in the resolution execution claim.
