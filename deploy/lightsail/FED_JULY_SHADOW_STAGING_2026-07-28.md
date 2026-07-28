# July 2026 FOMC decision staging checkpoint

Date: 2026-07-28

## Event contract

The July 29 FOMC decision is scheduled for `18:00 UTC` (`20:00` Budapest).
The reviewed pre-decision target range is `3.50%-3.75%`; Polymarket resolves
the markets from the change in the upper bound.

Five binary markets are bound to one event:

| Bucket | Rule on normalized change |
| --- | --- |
| No change | `== 0 bps` |
| Increase 25 | `== 25 bps` |
| Increase 50 or more | `>= 50 bps` |
| Decrease 25 | `== -25 bps` |
| Decrease 50 or more | `<= -50 bps` |

Nonstandard changes are normalized away from zero to the next 25-basis-point
bucket, matching the reviewed market resolution rule.

## Official sources

The poller races these official paths:

1. Federal Reserve Board statement HTML;
2. Federal Reserve Board implementation-note HTML;
3. Federal Reserve Bank of New York statement PDF;
4. Federal Reserve Board monetary-policy RSS, followed by the exact
   canonical statement URL.

Requests are HTTPS-only with exact host allowlists, bounded response sizes,
short timeouts, cache-busting for Board endpoints, and independent route
sessions. The first valid document wins; slow sources do not delay execution.
No source is polled unless at least one FED profile is enabled and in-window.

The parser requires the exact scheduled release date and one unambiguous
target range. It accepts decimal, mixed-fraction, and Unicode-fraction
representations plus the wording used for holds, rate changes, and
implementation notes. Conflicting target ranges fail closed.

## Historical official-document replay

The statement parser completed read-only replay against eight official Board
statements:

```text
2025-07-30  4.25%-4.50%
2025-09-17  4.00%-4.25%
2025-10-29  3.75%-4.00%
2025-12-10  3.50%-3.75%
2026-01-28  3.50%-3.75%
2026-03-18  3.50%-3.75%
2026-04-29  3.50%-3.75%
2026-06-17  3.50%-3.75%
```

This covers three cuts and five holds. The PDF extractor also parsed the
official New York Fed PDF for June 17, 2026 as `3.50%-3.75%`.

## Runtime path

One confirmed document follows the accepted architecture:

```text
Official FED source
  -> canonical ResolutionSignal
  -> five profile-scoped signal adapters
  -> five NumericThresholdStrategy rules
  -> five OrderIntent groups
  -> shared PreparedExecutor and tick supervision
```

Each market is independently claimed and executed. The event notification is
written to the durable Telegram outbox only after the five coordinator
attempts, so messaging cannot delay the trading path. The message includes
the winning official source URL and all five evaluated outcomes.

## Staging database

A fresh staging PostgreSQL backup completed before mutation.

The transactional seed
`017_add_fed_july_shadow_profiles.sql` and the read-only fail-closed check
`verify_fed_july_shadow_profiles.sql` passed.

All five profiles use the default account template:

```text
account=abccbaq
yes_price=0.999
no_price=0.999
quantity=50
lifecycle=reprice_on_tick_change
old_tick=0.01
new_tick=0.001
```

They remain `DISABLED`. Their schedules are `AUTO_PREFLIGHT / PENDING`, with
preflight at `17:30 UTC`, activation eligibility at `17:55 UTC`, and expiry
at `18:20 UTC`. The aggregate reviewed notional is `249.75`, below the
existing `1000` cap, and no execution claim exists.

## Verification and deployment boundary

The complete suite passed: `666` tests with one skip. The repository secret
scan passed. Production, Docker services, and live trading were not changed.

Before this event can trade, a later stage must:

1. build and promote an immutable image containing the FED worker and PDF
   dependency;
2. apply the guarded seed and check to production;
3. run authenticated preflight for all five markets;
4. receive separate approval to promote the schedules to `AUTO_LIVE`.
