# July 29 POST_MARKET review

The live block is closed at the profile/source level:

- live monitoring automation deleted;
- resolution profiles: `0`;
- profile-gated public polling scopes: `0`;
- profile-gated SEC-current polling scopes: `0`;
- the global SEC-API WebSocket remains connected;
- HOOD is `COMPLETED`/`DISABLED`;
- EA is `BLOCKED`/`DISABLED` with
  `official_schedule_unconfirmed`;
- MSFT is `COMPLETED`/`DISABLED` and retains its parser quarantine evidence.

Completing a profile does not cancel an accepted exchange order. At
2026-07-29 22:14 UTC, read-only remote inspection confirmed that the delayed
WAY replacement was still open for 100 shares at limit `0.999`, with zero
matched. Repeated SBUX replacement inspection returned a sanitized
`UnexpectedResponseError`, so its remote state was not proven. Cancelling
either order requires a separate explicit operator decision.

## Outcomes

| Ticker | Winner | Value / decision | Source observed | Claim / exchange | Result |
| --- | --- | --- | --- | --- | --- |
| META | PR Newswire poll | `6.18 < 7.20`, NO | 20:02:03.430 | 38 ms / 329 ms | accepted at limit `0.999`; latency miss |
| QCOM | SEC current poll | `2.21 < 2.23`, NO | 20:02:19.099 | 27 ms / 127 ms | accepted at limit `0.999`; latency miss |
| WAY | SEC-API WebSocket | `0.43 > 0.40`, YES | 20:02:23.030 | 39 ms / 147 ms | 100 filled; operator observed fill near `0.76`; success |
| SBUX | SEC current poll | `0.91 > 0.69`, YES | 20:06:45.688 | 28 ms / 51 ms | 50 accepted at `0.99`, repriced to `0.999`; latency miss |
| MSFT | SEC-API WebSocket | conflicting GAAP EPS values | 20:06:06.032 | none | parser quarantine; no trade |
| HOOD | SEC-API WebSocket | `0.62 > 0.43`, YES | 20:06:07.919 | none | preflight never reached READY; no trade |
| EA | none | official date unconfirmed | none | none | blocked intentionally |

Claim latency is measured from parsed fact detection to claim creation.
Exchange latency is measured from claim creation to the stored terminal
submission acknowledgement. It is not the source-arrival race.

## Source-arrival latency

The dominant delay was before parsing:

| Ticker | Issuer/provider timestamp | First observation | Arrival delay |
| --- | --- | --- | --- |
| META / PR Newswire | 20:01:00 | 20:02:03.430 | 63.430 s |
| QCOM / SEC current | 20:01:35 | 20:02:19.099 | 44.099 s |
| WAY / SEC-API WS | 20:01:48 | 20:02:23.030 | 35.030 s |
| MSFT / SEC-API WS | 20:04:53 | 20:06:06.032 | 73.032 s |
| HOOD / SEC-API WS | 20:05:14 | 20:06:07.919 | 53.919 s |
| SBUX / SEC current | 20:06:12 | 20:06:45.688 | 33.688 s |

META proves the value of independent public sources: PR Newswire produced the
tradable fact about 115 seconds before the SEC-API WebSocket duplicate. For
the other tickers, 28–186 ms of internal decision/exchange work was small
relative to 34–73 seconds of source arrival.

Current persistence records a late duplicate only when that route still runs
after the winner. Profile-gated polling stops with profile completion, so the
system cannot yet produce a complete winner/runner-up table for every event.
The next source telemetry change should keep non-winning routes in
observation-only mode for 10–15 minutes and persist:

- provider publication timestamp;
- first transport observation;
- fetch start/completion and route;
- parse completion and value;
- `source_race_lag_ms` from the first valid provider;
- winner, runner-up, and validation disagreement.

## HOOD incident

The SEC document was fetched in 44 ms and parsed correctly. The fact was
`VALIDATED`, matched the production rule, and no live execution claim or order
group existed.

The last lifecycle transition before manual completion was
`PREFLIGHT_BLOCKED` with `authenticated_preflight_not_ready`. The profile
therefore never entered the resolution worker. A fresh authenticated,
non-submitting probe later prepared and pre-signed both outcomes successfully,
which makes the original failure transient but not reconstructible: the old
worker discarded the per-template error and persisted only the generic code.

The local fix keeps a failed attempt in `PREFLIGHTING`, classifies the safe
cause, and retries every 10 seconds until the scheduler's activation grace
ends. Persistent failure still blocks activation.

## WAY supervision incident

The initial order was accepted at 20:02:23.530. The `0.01 -> 0.001` tick event
was not observed until 20:10:26.671. Submit-first immediately placed a full
100-share replacement, but cancellation of the source order reported that it
was already cancelled or matched. Recovery then proved that the source was
filled and the replacement did not match the zero remaining quantity.

The local fix preserves submit-first for a fresh tick event. When the tracked
order is more than five seconds old, the supervisor first performs an exact
read:

- fully filled: complete without replacement;
- partially filled: replace only the remaining quantity/notional;
- inspection unavailable or unknown: fail closed.

## Next improvements

1. Deploy and verify the preflight-retry and stale-reprice fixes before the
   next live block.
2. Add a safe block-close operation that reports all remotely open tracked
   orders and requires an explicit keep/cancel choice.
3. Persist actual average fill price and fill notional; limit price alone
   cannot explain the successful WAY fill near `0.76`.
4. Add observation-only source tails and make `source_race_lag_ms` the primary
   source KPI.
5. Add faster official company/wire paths ticker by ticker; internal hot-path
   work is already sub-400 ms and is not the main bottleneck in this run.
6. Harden MSFT parsing with an explicit, market-definition-aligned GAAP EPS
   selector and replay it against historical releases before re-enabling.
