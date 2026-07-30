# SEC Latest Filings source — 2026-07-30

Status: implementation and local verification complete; initial inactive
staging startup passed; final observation-only image rollout pending.

## Purpose

The July 29–30 source audits showed that post-signal parsing and execution are
normally sub-second while SEC source discovery can take tens of seconds. The
existing `sec_current` path polls one submissions JSON document per active
CIK. The SEC describes Latest Filings and its feed as the resource intended
for close-to-real-time availability:
<https://www.sec.gov/about/webmaster-frequently-asked-questions>.

## Runtime contract

`sec_latest_filings_atom` is an independent transport alongside:

- `sec_api_websocket`;
- `sec_current_poll`;
- issuer IR and press-wire polling.

The new transport:

- makes one conditional Atom request for all active earnings CIKs;
- makes no request when no earnings profile or observation tail is active;
- accepts only an initial `8-K` for an active CIK with Item 2.02;
- requires a bounded acceptance-time lookback and a valid accession;
- allowlists the exact SEC feed and filing-index URL shapes;
- reuses the existing official filing-index parser, exact `EX-99.1` router,
  parallel exhibit fetcher, issuer parser, and event deduplication;
- records `transport_observed_at` when the feed is received, before filing
  index and exhibit download;
- starts with a transport-specific observation-only guard, so even an active
  profile can record an `OBSERVED` fact but cannot receive a signal from this
  route;
- keeps a separate completed-event set so a losing transport still records
  source-race telemetry;
- uses the existing observation-only tail after a schedule becomes terminal.

Production configuration caps per-CIK submissions polling at four requests
per second and Latest Filings polling at four requests per second. This leaves
headroom below the SEC ten-request-per-second fair-access ceiling for the
winning exhibit request.

## Verification

- The parser was checked against the live official SEC Atom response.
- Unit tests cover routing, active-CIK filtering, one-request fan-in,
  conditional requests, stale entries, URL fail-closed behavior, profile
  gating, and feed-arrival timestamps.
- Full repository suite: `928` tests passed, `1` skipped.
- Secret scan passed.

The first immutable staging image
`sha256:03126e975e77e2f9deba2845cbd04f60fb4d2321f44a3a5f6dcdcdf180dcfe23`
started with restart count `0`. Its startup and first heartbeat confirmed:

- `sec_latest=True`;
- no active or tail scopes;
- zero Latest Filings polls;
- SEC-API WebSocket connected with `39` watches;
- `errors=0`.

The observation-only guard was added after this inactive startup. A new exact
image must repeat the same staging check before production changes.
