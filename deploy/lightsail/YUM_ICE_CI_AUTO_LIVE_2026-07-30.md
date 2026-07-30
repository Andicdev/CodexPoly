# YUM, ICE, and CI AUTO_LIVE production checkpoint — 2026-07-30

## Authorized scope

The operator authorized only these production schedules:

- `schedule:earnings-yum-2026q2`;
- `schedule:earnings-ice-2026q2`;
- `schedule:earnings-ci-2026q2`.

The approved per-order quantity/notional and aggregate limits remain
`100 / 100 / 1000`. Each selected outcome has reviewed notional `99.9`;
the three new profiles total `299.7`, and together with the already armed
VIRT and MA profiles the reviewed total is `499.5`.

## Guarded transition

Migration `034_arm_yum_ice_ci_july_30_premarket.sql`:

- rejected execution at or after `10:00 UTC`;
- validated the exact schedules, profiles, rules, account, prices, quantity,
  lifecycle policy, market identifiers, and aggregate notional;
- rejected existing validated facts, claims, and active/repricing groups;
- required a fresh fully-live resolution heartbeat;
- changed only the three schedules from `AUTO_PREFLIGHT` to `AUTO_LIVE`;
- left all three execution profiles `DISABLED` for scheduler-owned activation.

The production migration and independent read-only arming verifier completed
successfully.

## Authenticated preflight

The readiness worker reported:

- YUM ready at `09:45:08 UTC`;
- ICE ready at `09:45:09 UTC`;
- CI initially deferred once with
  `authenticated_preflight_not_ready`, then ready at `09:45:31 UTC`.

No schedule was blocked. The strict read-only post-preflight verifier passed
at `09:47:10 UTC`: all three schedules were `READY`, readiness evidence and
leases were valid, the execution profiles remained `DISABLED`, and the live
resolution heartbeat was fresh with supervision and trading enabled.

The scheduler owns activation at `10:00 UTC`. A stale readiness result or any
subsequent guard failure must block activation rather than enable a profile.

## Runtime evidence

All five production workers were running image digest
`sha256:ab7f30da8b52cc4021c68f45435a0016c18b746e7ff5740b23807cea68b84545`.
The sanitized SEC heartbeat showed `connected=True`, `watches=25`, and
`errors=0`.
