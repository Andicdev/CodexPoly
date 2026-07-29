# Earnings source telemetry — step 2

Status: implemented locally; not applied to staging or production.

## Purpose

The July 29 audit showed that execution after a validated fact is already
sub-second, while source discovery and some public-source parsers dominate the
end-to-end delay. Step 2 makes those stages independently measurable without
changing source routing, resolution semantics, strategy, order intent, or the
executor.

## Exact source paths

Every new candidate carries one of these transport values:

- `sec_api_websocket`;
- `sec_current_poll`;
- `company_ir_poll`;
- `press_release_rss_poll`;
- `globenewswire_poll`;
- `businesswire_poll`;
- `prnewswire_poll`;
- `seeking_alpha_poll`;
- `legacy_unknown` for historical or unclassified rows.

SEC exhibit downloads additionally record the winning `sec_direct` or
`sec_api_archive` route. Public documents record `public_document` or
`public_pdf_text`.

## Measured timestamps

For the transport that is actually processed:

1. `transport_observed_at`;
2. `document_fetch_started_at`;
3. `document_fetch_completed_at`;
4. `parse_started_at`;
5. `parse_completed_at`;
6. `fact_persisted_at`.

The run journal derives:

- publication to transport observation;
- transport observation to fetch start;
- document fetch duration;
- parser duration;
- fact persistence duration;
- transport observation to durable fact.

`earnings_source_transport_observations` also retains the first and last time
each transport saw a deduplicated event. This allows a direct comparison of
SEC WebSocket versus SEC current polling and of IR versus wire discovery,
including when only one transport wins processing.

## Database compatibility

Migration `016_add_earnings_source_telemetry.sql` creates only:

- `earnings_source_processing_telemetry`;
- `earnings_source_transport_observations`.

It does not alter `earnings_source_events` or any other existing table. The
previous production image can therefore continue running or be restored after
the migration. Existing source rows are backfilled as `legacy_unknown`.

First-seen event, processing telemetry, and transport observation are inserted
by one SQL statement and one application/database round trip. Existing status
updates also persist stage timings in their current round trip.

## Operational verification

After migration 016 and the matching image are explicitly approved and
deployed, use the guarded read-only query:

`deploy/lightsail/checks/diagnose_earnings_source_telemetry.sql`

No production mutation is part of step 2.
