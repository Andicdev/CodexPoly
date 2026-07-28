# July 29 SEC earnings batch staging checkpoint

Date: 2026-07-28

## Market discovery

The public Polymarket Gamma API returned active, open July 29 EPS markets for
all 24 requested tickers. Market slug, condition ID, GAAP/non-GAAP basis, and
strike were recorded.

Eight lower-ambiguity SEC filers were promoted from research to implemented
parser/rule/profile configuration:

| Ticker | Market metric | Strike | Expected UTC |
|---|---:|---:|---:|
| SOFI | GAAP diluted EPS | `0.11` | `11:00` |
| PG | quarterly core non-GAAP EPS | `1.41` | `11:00` |
| HUM | adjusted non-GAAP EPS | `7.00` | `10:00` |
| QCOM | headline non-GAAP EPS | `2.23` | `20:05` |
| MSFT | GAAP diluted EPS | `4.21` | `20:05` |
| META | GAAP diluted EPS | `7.20` | `20:05` |
| EBAY | headline non-GAAP diluted EPS | `1.51` | `20:05` |
| HOOD | GAAP diluted EPS | `0.43` | `20:05` |

The other 16 tickers are stored in `earnings_release_catalog` as
`RESEARCH_PENDING`: WING, ARCC, IART, GRMN, CBRE, PAG, ETSY, SONO, ARM, WAY,
EA, MGM, ORLY, TDOC, CMG, and CVNA. No executable rule, profile, or schedule
was created for this backlog.

## Historical official-document replay

Each implemented parser was run against a real previous official release.
Only the selected values were retained in the audit:

```text
SOFI   0.12
PG     1.48
HUM   10.31
QCOM   2.65
MSFT   4.27
META  10.44
EBAY   1.66
HOOD   0.38
```

The PG parser selected quarterly core EPS even though the same document also
contained full-year core EPS. The META parser was tightened after the first
replay so that a tax-effect footnote could not become a second EPS candidate.
The final replay produced one value for every parser.

## Staging database

A fresh staging PostgreSQL backup completed before mutation.

The following transactional seeds and read-only guards passed:

- `015_add_july_29_sec_profiles.sql`;
- `verify_july_29_sec_profiles.sql`;
- `016_catalog_remaining_july_29.sql`;
- `verify_july_29_catalog_backlog.sql`.

The eight profiles use the default account template:

```text
account=abccbaq
yes_price=0.999
no_price=0.999
quantity=50
lifecycle=reprice_on_tick_change
old_tick=0.01
new_tick=0.001
```

All eight profiles remain `DISABLED`. Their schedules are
`AUTO_PREFLIGHT / PENDING`, not `AUTO_LIVE`. Aggregate reviewed notional is
below `1000`, and no execution claim exists.

## Deployment boundary

Production was not changed. The production workers were not restarted while
the July 28 morning live window was approaching.

Before these profiles can trade, a later stage must:

1. build and promote an immutable image containing the new parsers;
2. apply the guarded seeds and checks to production;
3. complete authenticated preflight;
4. receive separate approval to change the eight schedules to `AUTO_LIVE`.

EBAY's date/session remains catalogued as estimated until an official
announcement page is confirmed. Its disabled profile must not be armed while
that status remains unresolved.
