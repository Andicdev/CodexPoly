# Full neg-risk catalog staging checkpoint

Date: 2026-07-30

## Deployment

The read-only full-catalog scanner is running on `codexpoly-host-02` in the
isolated staging stack. The deployed source revision is `20147fa`. The
rootless Docker image is pinned by immutable ID:

```text
sha256:e794d105ff82d464f492cfda3274b103594fffafe68fb81098391bfbde00609a
```

Its OCI revision label is `20147fa`. The source archive SHA-256 is:

```text
f610618a181bcfaf8d0370c2ddb957b42b7ac475c35b3ebf508416d4459e47ac
```

Only `neg-risk-catalog` was recreated. The existing September FED public
WebSocket recorder was not restarted and remains pinned to its prior image.
Production was not changed.

## Catalog path

Every 15 minutes the scanner exhausts the official public Gamma
`/markets/keyset` cursor with `closed=false`, then applies the active,
non-archived, `negRisk=true` filter locally. It persists current event and
market:

- volume windows, liquidity, open interest, prices, spread, and order status;
- fee type, fee schedule, rebate rate, and derived fee category/profile;
- tick profile, minimum order size, reward size/spread terms, and tail legs;
- issue codes and a conservative launch-screening status.

Each page is written only into scan-scoped staging tables. The current
snapshot is replaced in one transaction after cursor exhaustion; failed or
partial scans leave the last complete snapshot visible.

The first complete staging traversal observed:

```text
pages=1177
gamma_markets=117622
neg_risk_markets=46842
stored_markets=46842
events=7436
ready_for_l2_replay=6075
issues=105
skipped_markets=0
duration_ms=116817
live_orders_enabled=false
```

`READY_FOR_L2_REPLAY` means only that public catalog metadata is complete
enough for the next measurement stage. It is not a trading signal.

## Reporting

A safe read-only JSON report exposes the latest complete scan, category and
fee/tick profile totals, and top metadata-complete candidates:

```text
python -u -m neg_risk_trading.catalog_report --top 20
```

The staging report confirmed that `fed-decision-in-september-762` ranks first
globally by the current public volume/liquidity screen. It also found active
fee-free neg-risk events, which remain candidates for explicit fee and L2
verification before any strategy decision.

## Safety and verification

The service has no published port, trading-account secret, private key, CLOB
credential, Telegram credential, or order executor. It receives only the
isolated staging database password file. Shadow mode is mandatory and the
database rejects `live_orders_enabled=true`.

The catalog schema check and post-start active-scan check passed. The
repository secret scan passed. The complete Python 3.12 suite passed:
`915` tests with one skip. The image build repeated both checks successfully
inside the clean source archive.
