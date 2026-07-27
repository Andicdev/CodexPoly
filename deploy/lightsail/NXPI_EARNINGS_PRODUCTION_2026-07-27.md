# NXPI earnings production shadow checkpoint — 2026-07-27

## Reviewed release

- NXPI source commit: `34decc8`.
- Runtime and source-notification hardening commit: `88068bf`.
- Public earnings sources commit: `971dd7f`.
- Clean source archive SHA256:
  `b13c1e27dffc3ca9838b402806cd676fc6673cb575cea949db87736e2e094ab7`.
- Image archive SHA256:
  `eda1ea83d16e3e135b8fc862e678af3d22a2edc4ddc8f24cba9fa2d6aeed886f`.
- Immutable image:
  `codexpoly@sha256:ee5a90600611281320d27062a42e15cd56dca9718de6ad3476095b0a98c7670a`.

The clean Docker build passed the repository secret scan and all `576`
tests. The local working-tree run passed the same `576` tests with one skip
before the release commits were created.

## Production database state

The idempotent seed
`deploy/lightsail/seeds/005_add_nxpi_earnings.sql` and the fail-closed check
`deploy/lightsail/checks/verify_nxpi_earnings.sql` passed through the
production migration runner.

- Rule: `nxpi-2026q2-nongaap-eps-3pt53`.
- Scope: `earnings:NXPI:2026Q2`.
- Rule status: `SHADOW`.
- Execution profile: `earnings-nxpi-2026q2`.
- Profile status: `DISABLED`.
- No NXPI execution claim exists.
- No order was prepared or submitted.

The rule resolves YES only when NXP's initially announced primary headline
non-GAAP EPS is strictly greater than `3.53` USD after ordinary two-decimal
rounding.

## Source paths

The production rule has three independent official transports:

1. the continuously connected shared SEC-API WebSocket and Item 2.02
   EX-99.1 document route;
2. the NXP investor-relations RSS feed and company document;
3. the GlobeNewswire earnings RSS feed and full release document.

The public pollers are gated by enabled in-window earnings profiles. They are
currently inactive because the NXPI profile and every other execution profile
are disabled. The SEC WebSocket remains connected independently.

## Promotion evidence

The same immutable image was first loaded into rootless staging. NXPI parser
and source-notification contract smoke tests passed `12/12`. Both staging
workers started on the reviewed digest.

All three production base workers were then recreated from the same digest:

- `earnings-worker`;
- `notification-worker`;
- `resolution-worker`.

The trading overlay was not used. Name-only secret checks passed:

- earnings worker: database and SEC source secret names only;
- notification worker: database and Telegram secret names only;
- resolution worker: database secret name only.

The production source heartbeat reported:

```text
connected=True
watches=5
processed=0
signals=0
public_active=False
public_scopes=0
public_polls=0
ledger_active=False
errors=0
```

The resolution worker reported no enabled earnings or MSTR profiles.

## Telegram source links

The original MSTR summary was truncated because the generic log sanitizer
limited notification text to `240` characters. Source notifications now:

- preserve their multiline layout;
- allow up to `4000` sanitized characters;
- place `Source document: https://...` immediately below the provider;
- add a distinct `Filing: https://...` link when available.

Both URLs remain ordinary HTTPS text, so Telegram renders them as clickable
links without a parse mode.

The already delivered MSTR message cannot be edited. A separate idempotent
follow-up was therefore enqueued from the accepted append-only SEC event by
`deploy/lightsail/notifications/001_enqueue_mstr_source_links_2026_07_27.sql`.
The notification worker confirmed delivery on the first attempt. No trading
or MSTR audit state was modified.

## Safe next step

Keep `earnings-nxpi-2026q2` disabled until the guarded preflight and explicit
activation shortly before the reviewed July 28 preparation window. Enabling
the profile will start the two public pollers for NXPI; the SEC WebSocket is
already listening.
