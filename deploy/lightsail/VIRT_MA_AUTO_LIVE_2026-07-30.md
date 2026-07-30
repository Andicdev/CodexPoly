# VIRT and MA AUTO_LIVE production checkpoint — 2026-07-30

## Authorized scope

The operator explicitly authorized only these two production schedules:

- `schedule:earnings-virt-2026q2`;
- `schedule:earnings-ma-2026q2`.

The approved limits remain:

```text
CBR_LIVE_MAX_ORDER_QTY=100
CBR_LIVE_MAX_NOTIONAL=100
CBR_LIVE_MAX_TOTAL_NOTIONAL=1000
PROFILE_SCHEDULER_MAX_TOTAL_NOTIONAL=1000
```

Each profile has quantity `100`, desired YES and NO price `0.999`, and
reviewed worst-selected-outcome notional `99.9`. Their combined reviewed
notional is `199.8`.

## Guarded transition

Migration `033_arm_virt_ma_july_30_premarket.sql`:

- locked and validated both reviewed schedules;
- required both profiles to remain `DISABLED`;
- required both market rules to remain `SHADOW`;
- rejected validated/emitted facts, execution claims, and active/repricing
  order groups;
- required a fresh live resolution heartbeat with supervision and trading
  enabled;
- changed only the two schedules from `AUTO_PREFLIGHT` to `AUTO_LIVE`;
- set `armed_for_live=true` without directly enabling either profile.

The production migration and the independent read-only verifier both
completed successfully.

## Immutable evidence

- Arming commit: `b5b5194`
- Source archive SHA256:
  `1242ada4d3e943e66d4b682e69d38100c614ac4e3547367d1fe339540a97a534`
- Existing runtime image:
  `codexpoly@sha256:2db97c1f69ece6319b428e0a4b815814030041bcead6300556c41ff1c2c4a3cc`

No runtime code changed, so no worker restart or image replacement was
required. The local repository passed the secret scan and all 827 tests. The
immutable server build passed its scoped secret scan and all three arming
tests.

## Automatic checkpoints

At `2026-07-30 09:03 UTC`, both schedules were armed but the profiles remained
disabled, as expected before their TTL windows:

| Ticker | Preflight | Earliest activation | Deactivation |
| --- | --- | --- | --- |
| VIRT | 10:00 UTC | 10:30 UTC | 13:30 UTC |
| MA | 10:30 UTC | 11:00 UTC | 14:30 UTC |

The scheduler owns authenticated non-submitting preflight and activation. A
failed or stale preflight must block activation rather than enable a profile.

Final sanitized health markers showed:

- SEC WebSocket `connected=True`, 22 watches, and zero errors;
- live resolution heartbeat fresh with zero profiles before activation;
- readiness idle before the TTL windows;
- scheduler `auto_live=True` with no premature request or activation;
- all relevant containers running the expected digest with restart count
  zero.
