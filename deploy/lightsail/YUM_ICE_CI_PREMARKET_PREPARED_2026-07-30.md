# YUM, ICE, and CI PRE_MARKET prepared deployment — 2026-07-30

## Official timing

| Ticker | Official evidence | Expected release | Call/event |
| --- | --- | --- | --- |
| YUM | Issuer announcement | 11:00 UTC | 12:15 UTC |
| ICE | Issuer-confirmed call; historical release estimate | 11:30 UTC | 12:30 UTC |
| CI | Issuer release-details announcement | no later than 10:30 UTC | 12:30 UTC |

YUM's release time is explicitly stated by the issuer. ICE explicitly confirms
the 08:30 ET call, while 07:30 ET is recorded only as a historical release
estimate. Cigna's event card labels the 08:30 ET call as the earnings event,
but the issuer's separate release-details announcement says that financial
results will be available no later than 06:30 ET. The event-card timestamp is
therefore not a publication timestamp.

The phrase `no later than 06:30 ET` is an upper bound, not an exact release
time and not an earliest-signal floor. CI must be active before a conservative
PRE_MARKET session floor. The July 30 schedule happened to activate at
10:00 UTC and was live when the SEC document appeared at 10:16 UTC.

## Parsing contracts

- YUM: primary headline `EPS excluding Special Items`, strike `1.56`;
- ICE: primary headline `adjusted diluted EPS`, strike `1.84`;
- CI: primary headline `adjusted income from operations per share`, strike
  `7.60`.

Official first-quarter SEC EX-99.1 replays extracted YUM `1.50`, ICE `2.35`,
and CI `7.79`. The Cigna parser explicitly selects the per-share value after
the adjusted income amount, preventing the preceding billion-dollar amount
from becoming an EPS candidate.

Each rule has three discovery routes: always-on SEC-API WebSocket,
profile-gated SEC current-filings polling, and profile-gated Business Wire
RSS.

## Immutable deployment

- Commit: `55dd3ab`
- Source archive SHA256:
  `ff7300b8fd6505b99ec6433dbd1196a98ec494277f935e991a1cf175c041c957`
- Image:
  `codexpoly@sha256:ab7f30da8b52cc4021c68f45435a0016c18b746e7ff5740b23807cea68b84545`
- Image archive SHA256:
  `d95db1b1b7efab79f6ea9ed955331210d0b39430b711cd5c1a4c57c3b420f272`

The build passed the secret scan and all 835 tests.

## Production state

Seed 030 and its read-only verifier completed successfully. All three rules
are `SHADOW`, profiles are `DISABLED`, and schedules are
`AUTO_PREFLIGHT / PENDING`. There are no validated facts, execution claims,
or active order groups for these scopes.

All five workers run the immutable image with restart count zero. Sanitized
startup health showed 25 SEC watches: 24 earnings scopes and one MSTR scope.
The existing VIRT and MA schedules remained safely armed as `AUTO_LIVE`.

The three new schedules share:

- authenticated preflight at 09:45 UTC;
- earliest activation at 10:00 UTC;
- desired YES and NO price `0.999`;
- quantity `100` per profile;
- combined reviewed notional `299.7`;
- existing caps `100 / 100 / 1000`.

No new schedule can activate until separately authorized as `AUTO_LIVE`.
