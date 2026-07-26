# MSTR BTC production authenticated preflight checkpoint

Date: 2026-07-26

## Reviewed release

- Source commit: `124a63f`
- Source archive SHA256:
  `7140d9343104ed01f923b714900c9376646fe9c46fc5aa423d5e17c7ca5eea7a`
- Preflight image:
  `codexpoly@sha256:6e678f24b3d3619bac7bae59cee04483ac6bbd7916d5b382819c0dd8849f1fa8`
- Image archive SHA256:
  `3f02c7589b61d59cfa8213f4f90d4e82d783ad030deef9cb021f094733e6f8f6`
- Runtime user: `appuser`

The working tree passed the secret scan and 519 tests with one skip. The
clean image built from `git archive` independently passed the secret scan and
all 504 tests tracked by the reviewed commit.

The installed base and trading Compose files matched the copies in the clean
source archive byte for byte. No Compose replacement was required.

## Market readiness

Immediately before preflight, the public Gamma metadata reported all three
markets as active, open, accepting orders, and order-book enabled. Each
reported tick `0.01`, minimum order size `5`, and end time
`2026-07-28 04:00:00+00`.

The production account secret set passed the name-only checker for:

- `DATABASE_APP_PASSWORD`;
- `ACCOUNTS_MASTER_KEY`;
- `TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED`.

No secret value, balance, signed payload, token ID, or private wallet material
was printed or persisted in this checkpoint.

## Sequential authenticated preflight

The aggregate cap remained `100`. Consequently, only one MSTR profile was
enabled at a time. For every profile:

1. guarded SQL required all other profiles to be disabled and all MSTR
   execution claims to be absent;
2. the one-shot container ran in `preflight` mode with supervision and live
   trading disabled;
3. both outcome books were loaded and both GTC alternatives were pre-signed;
4. the common restore returned all three profiles to their checked-in
   `DISABLED` state;
5. the read-only invariant confirmed no MSTR execution claim existed.

Safe aggregate results:

| Profile | YES bid / ask | NO bid / ask | Tick | Effective price | Maximum prepared notional |
| --- | --- | --- | --- | --- | --- |
| `mstr-jul21-27-purchase-any` | `0.05 / 0.08` | `0.92 / 0.95` | `0.01` | `0.99` | `99` |
| `mstr-jul21-27-purchase-over-1000` | `0.02 / 0.61` | `0.39 / 0.98` | `0.01` | `0.99` | `99` |
| `mstr-jul21-27-sale-any` | `0.05 / 0.07` | `0.93 / 0.95` | `0.01` | `0.99` | `99` |

For all six alternatives:

- quantity was `50`;
- desired price was `0.999`;
- minimum-size validation passed;
- collateral sufficiency validation passed;
- authenticated pre-sign passed.

Every runner reported:

```text
order_submitted=false
source_fact_polled=false
executor_execute_called=false
```

## Restored production state

After the third preflight:

- all three MSTR profiles were `DISABLED`;
- all three checked-in preparation windows were restored;
- no MSTR execution claim existed;
- all ephemeral Compose run containers had been removed;
- the long-running `resolution-worker` was recreated from base Compose only;
- it runs in `shadow` mode with supervision disabled;
- it remains on
  `codexpoly@sha256:7b3a68c1b063304bce30dfc1e6712aed2ad73ed7f825b3702c4fdc1404bb7c83`;
- its only secret mount is `/run/secrets/DATABASE_APP_PASSWORD`;
- the trading overlay and trading-account secrets are not mounted to the
  long-running worker.

## Live activation remains blocked

The new hosted batch guard counts the conservative maximum selected outcome
across every enabled profile, including profiles owned by different source
workers. The three MSTR quantity-50 profiles total `149.85` at desired price
`0.999`, which exceeds the reviewed aggregate cap of `100`.

Before live mode, an explicit risk decision is therefore required: reduce the
enabled profile set or quantity, or approve a larger aggregate cap. No live
worker was started and no order was submitted in this checkpoint.
