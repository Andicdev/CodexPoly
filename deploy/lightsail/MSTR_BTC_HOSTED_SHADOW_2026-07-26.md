# MSTR BTC hosted shadow checkpoint

Date: 2026-07-26

## Reviewed release

- Source commit: `52b443b`
- Source archive SHA256:
  `7ad4025d23489f90f99eb5b6e60df60efb9ea7c65d232594076d8d221e24a992`
- Image:
  `codexpoly@sha256:7b3a68c1b063304bce30dfc1e6712aed2ad73ed7f825b3702c4fdc1404bb7c83`
- Image archive SHA256:
  `6ec261f1117bb6c05150ce3db7a74ef09f6c4d248bd0209a09f6ece2f189e2bd`
- Runtime user: `appuser`

The working-tree regression suite passed 508 tests with one skip. The image
was built from a clean `git archive`; its Dockerfile independently passed the
repository secret scan and all 493 tests contained in the reviewed commit.

## Checked-in markets

The public Gamma API metadata was checked on 2026-07-26. All three markets
were active, open, accepting orders, using tick `0.01` and minimum size `5`.
The hosted bindings use:

- purchase any:
  `0xa17d770b4962398a55d4b1d87e083ba986ab8fff4e8ca0c794fc3a4d1f18051a`;
- purchase greater than 1000 BTC:
  `0x53e75dd47cd2e9076955ca4e8e8827c5718dd1e9566d49d74a831b0465501ec1`;
- sale any:
  `0xc937afbe3ce062c934d2922c313a8990907f1d382a55e8ee56d36a5b0359500b`.

Their market window ends at `2026-07-28 04:00:00+00`. The execution
preparation window is checked in as `2026-07-27 06:00:00+00` through the
market end.

## Guarded profiles

`004_seed_disabled_resolution_profiles.sql` was applied first to staging and
then to production through the fixed migration runners. It created or updated
only these source-neutral profiles:

- `mstr-jul21-27-purchase-any`;
- `mstr-jul21-27-purchase-over-1000`;
- `mstr-jul21-27-sale-any`.

Every profile:

- belongs to account metadata `abccbaq`;
- remains `DISABLED`;
- requests `0.999` for either outcome and quantity `50`;
- uses one `0.01 -> 0.001` tick reprice;
- has no execution claim.

The read-only `005_verify_disabled_resolution_profiles.sql` invariant passed
in both environments before promotion and again after the staging smoke and
production restart.

## Persisted-fact staging smoke

Run id: `staging-52b443b-001`.

One parser-bypassed fact was written to the append-only staging audit under a
unique `staging-mstr-smoke-*` scope. Three temporary profiles exercised:

```text
mstr_btc_fact_candidates
    -> MstrBtcResolutionSource
    -> ResolutionSignal
    -> NumericThresholdStrategy
    -> OrderIntent
    -> DryRunPreparedExecutor
```

The selected outcomes were `YES / YES / NO`. Each market prepared two
templates, returned `DRY_RUN`, and reported `execution_attempted=false`.
`order_submitted=false`. The temporary profiles were returned to `DISABLED`.
The synthetic audit row remains immutable by design and cannot match a
production rule or scope.

## Promotion evidence

Only `resolution-worker` was recreated in staging and production. Both
instances run the reviewed immutable image and report separately that the
earnings and MSTR hosted workers have no enabled in-window profiles.

The production `earnings-worker` was not recreated and remains on:

`codexpoly@sha256:25c7fbabb910c1a0cdcacb2b8472a822fd433f9f52b438855f79f0cfabd6eaa9`

No `resolution-worker-trading` container was running. The base resolution
service received only its database secret; no trading account secret was
mounted. No authenticated market preflight or live execution occurred in
this checkpoint.
