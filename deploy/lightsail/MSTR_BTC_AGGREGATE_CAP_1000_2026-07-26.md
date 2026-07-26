# MSTR BTC aggregate cap 1000 checkpoint

Date: 2026-07-26

## Reviewed release

- Source commit: `cba91e5`
- Source archive SHA256:
  `c723ab93bd0a2a106f1eea68b840d70625d4db82fd6aa9df553dcd628e44a126`
- Image:
  `codexpoly@sha256:87afe79da54e739ecc001baf0bd22a8dd1d45c96ba621a339f87301bc5e32e4c`
- Image archive SHA256:
  `57653fee08198c0dce5a9a2e3d06feff45ebe52b77d0edc38f07e5a16b55111a`
- Runtime user: `appuser`

The working tree passed the secret scan and 522 tests with one skip. The
clean image independently passed the secret scan and all 507 tests tracked by
the reviewed commit.

## Risk policy

The reviewed production execution limits are now:

```text
CBR_LIVE_MAX_ORDER_QTY=50
CBR_LIVE_MAX_NOTIONAL=50
CBR_LIVE_MAX_TOTAL_NOTIONAL=1000
```

The quantity and per-order cap did not change. Only the aggregate cap changed
from `100` to `1000`.

## Combined authenticated preflight

Guarded SQL temporarily enabled exactly these three checked-in profiles:

- `mstr-jul21-27-purchase-any`;
- `mstr-jul21-27-purchase-over-1000`;
- `mstr-jul21-27-sale-any`.

The one-shot production runner authenticated all three profiles together and
prepared six outcome alternatives. It reported:

- enabled profiles: `3`;
- templates: `6`;
- maximum prepared-alternatives notional: `297`;
- maximum selected-outcomes notional: `149.85`;
- aggregate cap: `1000`;
- tick size: `0.01` for all six alternatives;
- desired price: `0.999`;
- effective price: `0.99`;
- quantity: `50`;
- minimum order size: `5`.

All six collateral checks and pre-sign operations succeeded. The runner
reported:

```text
order_submitted=false
source_fact_polled=false
executor_execute_called=false
```

No token ID, signed payload, balance, private wallet material, or secret value
was printed or persisted.

## Restored production state

After the combined preflight:

- all MSTR profiles were returned to `DISABLED`;
- the checked-in preparation windows were restored;
- the read-only invariant confirmed that no MSTR execution claim exists;
- the ephemeral preflight container was removed;
- `resolution-worker` was promoted to the reviewed image above;
- the long-running worker uses base Compose only;
- it runs in `shadow` mode with supervision disabled;
- its only secret mount is `/run/secrets/DATABASE_APP_PASSWORD`;
- the trading overlay and account secrets are not mounted.

No live worker was started and no order was submitted.
