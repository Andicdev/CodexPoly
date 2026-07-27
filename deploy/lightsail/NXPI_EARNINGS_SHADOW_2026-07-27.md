# NXPI earnings shadow checkpoint — 2026-07-27

## Market semantics

- Polymarket slug:
  `nxpi-quarterly-earnings-nongaap-eps-07-28-2026-3pt53`.
- Condition:
  `0x70676300a6fffc684d86850f30c8c34a64557f86c1f3fb377568bacb73585ff4`.
- Scope: `earnings:NXPI:2026Q2`.
- Resolution: YES only when the initially announced primary headline
  non-GAAP EPS is greater than `3.53` USD after standard rounding to two
  decimal places.
- Primary basis: diluted; fallback basis: basic.
- Official non-GAAP documents are primary. Seeking Alpha is the specified
  non-GAAP secondary source. The market permits a GAAP fallback after 96
  hours and resolves NO after 45 days without an earnings release.

## Source paths

The checked-in rule defines:

1. the shared SEC-API WebSocket, Item 2.02, EX-99.1 path;
2. NXP investor-relations RSS and company HTML;
3. GlobeNewswire earnings RSS and full HTML.

The parser accepts only NXP CIK `1413447`, the expected fiscal period, an
official-company authority, and the exact primary headline label:
`Non-GAAP diluted Net Income (Loss) per Share`.

GAAP EPS and forward guidance values are ignored. Multiple occurrences of the
same headline value are allowed; conflicting headline values are quarantined.

## Replay

The parser was run against the complete official NXP Q1 2026 investor
relations HTML. It returned:

```text
status=accepted
reason=official_nxp_headline_non_gaap_diluted_eps
value=3.05
```

## Staging state

The idempotent NXPI seed and fail-closed verification were applied to staging.
The execution profile uses the operator default:

- YES desired price `0.999`;
- NO desired price `0.999`;
- quantity `50`;
- tick reprice `0.01 -> 0.001`;
- one reprice.

The profile remains `DISABLED`, and the check confirms that no NXPI execution
claim exists.

Production seed and image deployment were deliberately deferred until after
the imminent MSTR publication window. No production worker or trading overlay
was changed during this checkpoint.

## Verification

- Secret scan: passed.
- Full local suite: 574 tests passed, 1 skipped.
- Staging SQL verification: passed.
