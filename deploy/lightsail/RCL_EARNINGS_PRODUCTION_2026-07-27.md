# RCL earnings production shadow checkpoint — 2026-07-27

## Reviewed release

- Source commit: `00ef68e`.
- Clean source archive SHA256:
  `09e567f2c06f370f056102a35285f6307c4359806597c6f0f268a5117b5e199a`.
- Image archive SHA256:
  `3cdf58ce1617c203f317dbfd0b9258ab328c1f7559a4c24024b1c8678cd9b95a`.
- Immutable image:
  `codexpoly@sha256:28b60b56e84cd1dd17a28423d487f490a284e4f030ddaa1a8b6d06d770dfd534`.

The clean VPS build passed the repository secret scan and all `590` tests.
The local working tree passed the same `590` tests with one skip before the
release commit was created.

## Market and database state

- Polymarket condition:
  `0x8701e9a10812190db05c6f703b4dd3d8d978ac171874c78bb26b2f23d7a38976`.
- Rule: `rcl-2026q2-nongaap-eps-3pt97`.
- Scope: `earnings:RCL:2026Q2`.
- Rule status: `SHADOW`.
- Execution profile: `earnings-rcl-2026q2`.
- Profile status: `DISABLED`.
- Preparation window: `2026-07-28 09:00:00Z` through
  `2026-07-28 17:00:00Z`.

The profile uses the shared default for account `abccbaq`: both outcomes at
`0.999`, quantity `50`, initial tick size `0.01`, target tick size `0.001`,
and at most one reprice. The rule resolves YES only when the initially
reported primary headline Adjusted diluted EPS is strictly greater than
`3.97` USD after two-decimal rounding.

The idempotent seed
`deploy/lightsail/seeds/007_add_rcl_earnings.sql` and fail-closed check
`deploy/lightsail/checks/verify_rcl_earnings.sql` passed through both staging
and production migration runners. The seed cannot enable the profile or
create an execution claim.

## Source paths

RCL has three independent official transports:

1. the continuously connected shared SEC-API WebSocket, routed through the
   RCL CIK, Item 2.02, and EX-99.1 policy;
2. the Royal Caribbean investor-relations HTML release listing and full
   company release;
3. the PR Newswire release RSS feed and full wire document.

The bounded HTML listing adapter recognizes release rows and applies the
explicit July EDT offset instead of depending on a host timezone database.
Both public sources are gated by an enabled, in-window profile and are
therefore inactive while the profile is disabled.

## Parser evidence

The production parser accepts only RCL's reported-quarter headline structure
that contains both reported EPS and Adjusted EPS. It does not select guidance,
definitions, or unrelated adjusted metrics.

- Official RCL Q1 2026 investor-relations release replay:
  accepted `3.60` USD.
- Official RCL Q2 2025 PR Newswire release replay:
  accepted `4.38` USD.
- Live staging source probe:
  two watches, two successful listings, zero errors, and zero current result
  candidates before the Q2 2026 release.

## Deployment evidence

The immutable image was deployed to rootless staging first. The staging
heartbeat reported:

```text
connected=True
watches=9
earnings_watches=8
mstr_watches=1
public_active=False
ledger_active=False
errors=0
```

The same digest was then deployed to all three production base workers:

- `earnings-worker`;
- `notification-worker`;
- `resolution-worker`.

The production heartbeat reported the same nine connected SEC watches, no
errors, and inactive public and ledger polling. The resolution worker reported
no enabled in-window earnings or MSTR profiles. The trading overlay was not
started, and no order was prepared or submitted.

## Safe next step

Keep `earnings-rcl-2026q2` disabled until a guarded authenticated preflight
and explicit live activation shortly before the July 28 preparation window.
Activation will start the two public pollers; the SEC WebSocket is already
listening.
