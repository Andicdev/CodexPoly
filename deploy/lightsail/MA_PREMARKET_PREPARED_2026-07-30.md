# MA PRE_MARKET prepared deployment — 2026-07-30

## Official schedule and market rule

- Mastercard confirmed second-quarter 2026 results for Thursday, July 30,
  with the conference call at 09:00 EDT (13:00 UTC).
- The release time is not stated by the issuer. The catalog therefore records
  08:00 EDT (12:00 UTC) only as a bounded historical estimate, not as an
  official timestamp.
- The Polymarket condition is strict: adjusted non-GAAP diluted EPS greater
  than `4.77` resolves YES.

The parser accepts only Mastercard's adjusted diluted EPS headline and rejects
guidance, outlook, GAAP-only, and table-only candidates. The official
first-quarter SEC exhibit replay extracted `4.60` as expected.

## Sources

The profile has three independent discovery routes:

1. the always-on SEC-API WebSocket for an 8-K Item 2.02 / EX-99.1;
2. profile-gated official SEC current-filings polling;
3. profile-gated Business Wire polling.

The issuer announcement says results will be posted on Mastercard Investor
Relations and distributed through a news-wire alert. No unverified Mastercard
IR RSS endpoint was added.

## Immutable boundary

- Feature commit: `8fb5f1a`
- Corrective seed commit: `2d05db8`
- Source archive SHA256:
  `0a31fd967780ca9bc11ad5226ad295d7e70429ac54018f5c651374dcf52e3872`
- Image:
  `codexpoly@sha256:2db97c1f69ece6319b428e0a4b815814030041bcead6300556c41ff1c2c4a3cc`
- Image archive SHA256:
  `b6bd3d38e1ba2b82343f90f88b566c1d720ba531d993c42cd3e2269925ff4848`

The immutable build passed the repository secret scan and all 824 tests.

## Staging

Seed 029 and the guarded MA verifier completed successfully. Both staging
workers were recreated on the immutable image with restart count zero.
Sanitized health markers confirmed:

- 36 SEC watches: 35 earnings scopes and one MSTR scope;
- zero active resolution profiles outside trading windows.

## Production

The safe-worker-restart guard passed before the deployment. The production
earnings worker was stopped before seed 029 was applied, so the previous image
could not observe the MA rule without the new parser.

The guarded verifier confirmed:

- rule `earnings-ma-2026q2` is `SHADOW`;
- profile `earnings-ma-2026q2` is `DISABLED`;
- schedule `schedule:earnings-ma-2026q2` is
  `AUTO_PREFLIGHT / PENDING`;
- `armed_for_live` is false;
- the MA scope has no validated fact, execution claim, or active order group.

All five production workers were recreated on the immutable image with the
existing live guards and caps:

```text
CBR_LIVE_MAX_ORDER_QTY=100
CBR_LIVE_MAX_NOTIONAL=100
CBR_LIVE_MAX_TOTAL_NOTIONAL=1000
PROFILE_SCHEDULER_MAX_TOTAL_NOTIONAL=1000
```

Final checks showed all five containers running with restart count zero.
Sanitized startup markers confirmed 22 SEC watches (21 earnings plus MSTR),
readiness in non-submitting mode, scheduler `auto_live=True`, and notification
schema readiness.

## Remaining release gate

This deployment does not authorize trading. The MA schedule remains
`AUTO_PREFLIGHT`, so it cannot enable the profile. Moving it to `AUTO_LIVE`
requires explicit operator authorization, authenticated non-submitting
preflight, a fresh live heartbeat, and the existing `100 / 100 / 1000` caps.
