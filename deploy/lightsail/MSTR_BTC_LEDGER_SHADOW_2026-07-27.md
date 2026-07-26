# MSTR BTC Strategy Ledger shadow checkpoint

Date: 2026-07-27 (Europe/Budapest)

## Scope

The production MSTR source now has two independent official transports:

- the existing shared SEC-API WebSocket route for the initial MSTR 8-K;
- a conditional HTTP poll of the structured Strategy Bitcoin Ledger.

Both transports persist the existing holdings-first fact contract and emit
the same source-neutral resolution signal IDs. No trading profile, intent,
claim, or order is created by the source worker.

## Reviewed release

- source commit: `aab98b7`;
- release archive SHA256:
  `d2a0c38260f323da5a3a22d4055cc9fb81dd18b0d38187418c321962b41a57aa`;
- immutable production image:
  `codexpoly@sha256:3f6513399066d99b6b8d670ae0bb3e429115eb7e791b4aed97c8c0ea268900ad`.

The image build repeated the repository secret scan and 523 clean-commit
tests. The full local workspace run completed 538 tests with one skip.

## Ledger invariants

The July 21-27 watch pins:

- baseline Ledger row: `116`;
- baseline holdings: `843775` BTC;
- database baseline holdings: `843775` BTC.

A new snapshot is eligible only when:

1. baseline row `116` still has exactly `843775` BTC;
2. every new row index is contiguous;
3. every signed BTC change reconciles to that row's running holdings;
4. the aggregate acquisition minus aggregate sale equals the final holdings
   change from the pinned database baseline;
5. detection occurs inside the checked-in event window.

Unchanged pages are suppressed by ETag and document fingerprint. A missing
SEC PDF does not invalidate the official Ledger observation; the Ledger URL
is used until a filing link is present.

## Production verification

The new image was promoted through the base Compose file only. Both
`earnings-worker` and `resolution-worker` use the exact immutable image.

The source heartbeat reported:

```text
connected=True watches=4 processed=0 signals=0 mstr_accepted=0
ledger_connected=True ledger_polls=28 ledger_accepted=0 errors=0
```

The public Ledger smoke from inside the production image reported:

```text
rows=116
latest_row_index=116
latest_holdings_btc=843775
accepted=False
reason=no_new_ledger_rows
```

The guarded read-only production disarmed check passed after the source
started polling. Therefore no MSTR source event, fact, processing result,
execution claim, or active supervision state exists for the live week.

## Safety state

- all MSTR and earnings execution profiles remain disabled;
- the resolution worker remains in shadow mode;
- the trading overlay is not running;
- the earnings worker receives only the database and SEC source secrets;
- the base resolution worker receives only the database secret;
- the Northflank duplicate source/orchestrator/legacy SEC services remain
  scaled to zero.

Live activation still requires the guarded release procedure and explicit
operator approval.
