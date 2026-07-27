# Earnings release catalog checkpoint — 2026-07-27

## Purpose

The additive `earnings_release_catalog` table preserves public research about
one scheduled earnings release per row:

- ticker and release date;
- pre-market, post-market, or unknown session;
- exact release time when the company publishes one;
- conference-call time kept separately from release time;
- official schedule evidence URL;
- known metric variants;
- tested SEC, company IR, and press-wire delivery options;
- document format and current integration effort.

The catalog is informational. It does not enable polling, create or update an
`earnings_market_rules` row, create an execution profile, arm trading, or
submit an order.

## Initial research

The idempotent seed contains 15 events researched on July 27:

- `PARSER_ONLY`: BA, CZR, CSGP, NXPI, and SBUX;
- `NEEDS_DOCUMENT_RESOLVER`: PYPL, HLT, SPGI, V, and F;
- `NEEDS_LISTING_ADAPTER`: RCL;
- `SOURCE_BLOCKED`: UPS, IVZ, KO, and JBLU.

Fourteen releases are scheduled for Tuesday, July 28. The official Starbucks
release is Wednesday, July 29, and is stored under that date rather than the
incorrect Tuesday grouping.

All metric options retain `market_basis=unverified`. A catalog entry therefore
cannot be promoted to an executable earnings market rule until the exact
Polymarket resolution basis has been checked.

## Database rollout

The following SQL files were applied first to staging and then to production
through the fixed stdin-only migration runners:

1. `cbr_trading/migrations/011_add_earnings_release_catalog.sql`;
2. `deploy/lightsail/seeds/004_seed_earnings_release_catalog_2026-07-28.sql`;
3. `deploy/lightsail/checks/verify_earnings_release_catalog_2026-07-28.sql`.

Both environments returned `MIGRATION_RESULT=applied`. The fail-closed check
confirmed all 15 event keys and all five `PARSER_ONLY` classifications without
printing catalog rows.

No worker or trading overlay was restarted.

## Verification

- Secret scan: passed.
- Full local suite: 566 tests passed, 1 skipped.
- New catalog tests: 5 passed.
