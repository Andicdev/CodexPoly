# MSTR BTC shared SEC shadow deployment checkpoint

Date: 2026-07-26

## Reviewed release

- Source commit: `2d4349a`
- Source archive SHA256:
  `2a5ae0ca5d61e93f6a297ad7bcad48ba438855423119cb6a63d8cfe24faca755`
- Image:
  `codexpoly@sha256:35e71d3c87808d54b2714c25cebd39530d9213bfb3aad76760af8ff7044968f4`
- Image archive SHA256:
  `3fdaecc8d7ff08909d562d1f5997de6fd33bcf9ac7b3425496ec4776ffe351c5`

The image was built from a clean `git archive`. Its Docker build passed the
repository secret scan and all 461 tests contained in the reviewed commit.

## Source boundary

The release replaces the earnings-specific transport boundary with:

```text
one SEC-API WebSocket
    -> SecFilingEnvelope
    -> EarningsRouter
    -> MstrBtcRouter
```

The existing earnings path remains compatible. The MSTR router accepts only
the watched issuer's initial primary `8-K` inside the Jul 21–27 event window.
It pins the validated holdings state that existed before the window and runs
the holdings-first parser. It does not persist a canonical weekly MSTR fact,
update holdings state, emit a resolution signal, create an execution profile,
or reach a trading component.

## Promotion evidence

The immutable image was first started in the rootless staging stack. Its
heartbeat reported:

- `connected=True`;
- `watches=4`;
- `processed=0`;
- `signals=0`;
- `mstr_accepted=0`;
- `errors=0`.

The same digest was then loaded into production system Docker. Only
`earnings-worker` was recreated. Its heartbeat reported the same aggregate
state with four watches: NVTS, WWD, BBBY, and MSTR.

The production `resolution-worker` was not recreated and remained on
`sha256:2c408499ddd01367fe097586346bd6cbe5073f5c82b8831d4d642c839cf31c30`.
No trading-overlay container was running.

Previous staging and production Compose files were retained as
`compose.before-2d4349a.yml`.
