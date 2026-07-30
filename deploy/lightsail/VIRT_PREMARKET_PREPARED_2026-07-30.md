# VIRT PRE_MARKET prepared deployment — 2026-07-30

## Official schedule decision

- TDAY was not prepared for July 30. The issuer schedule places its second
  quarter release on August 6, 2026 before the NYSE open. Seed 027 records the
  calendar mismatch and asserts that no July 30 TDAY rule, execution profile,
  or schedule exists.
- VIRT is issuer-confirmed for July 30, 2026 before the US market open, with
  the conference call at 07:00 EDT (11:00 UTC).
- The Polymarket rule is strict: normalized adjusted non-GAAP EPS greater than
  `1.82` resolves YES.

Virtu published a preliminary estimate of exactly `1.82` on July 14. That
document is not the final earnings release. The parser and source policy
therefore quarantine preliminary or revision-subject material before a fact
can be validated.

## Immutable boundary

- Source commit: `9c12446`
- Source archive SHA256:
  `1496eb8ce0db99eb0f628d914e55407730b498dc97040a2562462539bb682c7d`
- Image:
  `codexpoly@sha256:5c3cfad6e6a097e3e0b6b9286c6a01c655de572ebce082e35dc55523f9e3e4e5`
- Image archive SHA256:
  `8a70c1087c5ff986babf2954fef028a4bcc73a0788cfc57c65e8a7da65520cf0`

The archive build passed the repository secret scan and all 820 tests. A
replay of the official first-quarter release extracted `2.24`; a replay of
the July 14 preliminary second-quarter release returned
`virt_preliminary_results_not_final` without a candidate.

## Staging

Seeds 027 and 028 and the guarded VIRT verifier completed successfully. The
staging workers were recreated on the immutable image. Sanitized health
markers confirmed:

- SEC WebSocket connected with 35 checked-in watches and zero errors;
- public and SEC-current polling inactive outside a profile window;
- zero active resolution profiles.

## Production

The safe-worker-restart guard passed before any runtime change. It confirmed
there was no enabled profile, active schedule, imminent activation, pending
claim, or active/repricing order group.

The production earnings worker was stopped before seeds 027 and 028 were
applied, preventing the previous image from observing the newly inserted VIRT
rule without its parser. The guarded verifier then confirmed:

- the VIRT rule exists in `SHADOW`;
- profile `earnings-virt-2026q2` is `DISABLED`;
- schedule `schedule:earnings-virt-2026q2` is
  `AUTO_PREFLIGHT / PENDING`;
- the VIRT scope contains no validated fact, execution claim, or active order
  group;
- no July 30 TDAY trading configuration exists.

All five workers were recreated on the immutable image with the existing live
guards and caps:

```text
CBR_LIVE_MAX_ORDER_QTY=100
CBR_LIVE_MAX_NOTIONAL=100
CBR_LIVE_MAX_TOTAL_NOTIONAL=1000
PROFILE_SCHEDULER_MAX_TOTAL_NOTIONAL=1000
```

Final sanitized health markers showed:

- SEC WebSocket connected with 21 production watches and zero errors;
- live resolution healthy with zero managed profiles;
- readiness worker non-submitting and idle;
- scheduler healthy with `auto_live=True` and no transition requested;
- notification worker with zero failures;
- all five containers running the exact image digest with restart count zero.

## Remaining release gate

This deployment does not authorize trading. The schedule remains
`AUTO_PREFLIGHT`, so it cannot enable the profile. Before changing it to
`AUTO_LIVE`, require an explicit operator authorization, an authenticated
non-submitting preflight, a fresh live heartbeat, and the existing
`100 / 100 / 1000` caps.
