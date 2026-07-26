from __future__ import annotations

import unittest
from datetime import datetime, timezone

from cbr_trading.mstr_btc import (
    MstrBtc8KParser,
    MstrBtcDocumentCandidate,
    MstrBtcHoldingsBaseline,
    MstrBtcParseStatus,
    MstrBtcProvider,
    MstrBtcValueDerivation,
)


_FILED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
_DETECTED_AT = datetime(2026, 7, 20, 12, 0, 2, tzinfo=timezone.utc)


def _source(event_id: str = "0001193125-26-0308369") -> MstrBtcDocumentCandidate:
    return MstrBtcDocumentCandidate(
        scope_id="mstr-btc:2026-07-21:2026-07-27",
        provider=MstrBtcProvider.SEC,
        provider_event_id=event_id,
        ticker="MSTR",
        cik="1050446",
        form_type="8-K",
        source_url="https://www.sec.gov/mstr-btc-update.htm",
        filing_url="https://www.sec.gov/mstr-8k.htm",
        filed_at=_FILED_AT,
        received_at=_DETECTED_AT,
        transport_fingerprint=f"transport-{event_id}",
    )


def _baseline(holdings: int) -> MstrBtcHoldingsBaseline:
    return MstrBtcHoldingsBaseline(
        state_id=f"holdings-{holdings}",
        holdings_btc=holdings,
        as_of=datetime(2026, 7, 19, 23, 59, tzinfo=timezone.utc),
        provider=MstrBtcProvider.SEC,
        provider_event_id="baseline-accession",
        source_url="https://www.sec.gov/mstr-baseline.htm",
    )


def _parse(document: str, *, holdings_before: int):
    return MstrBtc8KParser().parse(
        document,
        source=_source(),
        baseline=_baseline(holdings_before),
        detected_at=_DETECTED_AT,
    )


class MstrBtc8KParserTests(unittest.TestCase):
    def test_purchase_layout_ignores_billion_dollar_price(self) -> None:
        # Mirrors the May 18 filing: purchase price changed from millions
        # to billions, while the BTC quantity and final holdings stayed stable.
        result = _parse(
            """
            <h2>BTC Update</h2>
            <table>
              <tr>
                <td>BTC Acquired (1)</td>
                <td colspan="2">Aggregate Purchase Price (in billions) (2)</td>
                <td colspan="2">Average Purchase Price (2)</td>
                <td>Aggregate BTC Holdings</td>
              </tr>
              <tr>
                <td>24,869</td>
                <td>$</td><td>2.14</td>
                <td>$</td><td>80,985</td>
                <td>843,738</td>
              </tr>
            </table>
            <h2>ATM Update</h2>
            """,
            holdings_before=818_869,
        )

        self.assertEqual(result.status, MstrBtcParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.acquired_btc, 24_869)
        self.assertEqual(result.candidate.sold_btc, None)
        self.assertEqual(result.candidate.holdings_after_btc, 843_738)
        self.assertEqual(
            result.candidate.acquired_derivation,
            MstrBtcValueDerivation.EXPLICIT,
        )

    def test_sale_layout_extracts_sold_quantity(self) -> None:
        # Mirrors the June 1 filing, the first recent sale layout.
        result = _parse(
            """
            <h2>BTC Update</h2>
            <table>
              <tr>
                <td>BTC Sold</td>
                <td colspan="2">Aggregate Sale Price (in millions) (2)</td>
                <td colspan="2">Average Sale Price (2)</td>
              </tr>
              <tr><td>32 (1)</td><td>$</td><td>2.5</td></tr>
            </table>
            <table>
              <tr>
                <td>Aggregate BTC Holdings</td>
                <td colspan="2">Aggregate Purchase Price (in billions)</td>
              </tr>
              <tr><td>843,706</td><td>$</td><td>63.87</td></tr>
            </table>
            <h2>USD Reserve</h2>
            """,
            holdings_before=843_738,
        )

        self.assertEqual(result.status, MstrBtcParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.acquired_btc, None)
        self.assertEqual(result.candidate.sold_btc, 32)
        self.assertEqual(
            result.candidate.sold_derivation,
            MstrBtcValueDerivation.EXPLICIT,
        )

    def test_plural_heading_and_multiple_sale_periods_are_aggregated(self) -> None:
        # Mirrors July 6: one filing contains two sale subperiods.
        result = _parse(
            """
            <h2>BTC Updates</h2>
            <p>For the period June 29 through July 1:</p>
            <table>
              <tr><td>BTC Sold</td><td>Aggregate Sale Price</td></tr>
              <tr><td>1,363</td><td>$42.0 million</td></tr>
            </table>
            <table>
              <tr><td>Aggregate BTC Holdings</td></tr>
              <tr><td>846,000</td></tr>
            </table>
            <p>For the period July 2 through July 5:</p>
            <table>
              <tr><td>BTC Sold</td><td>Aggregate Sale Price</td></tr>
              <tr><td>2,225</td><td>$68.0 million</td></tr>
            </table>
            <table>
              <tr><td>Aggregate BTC Holdings</td></tr>
              <tr><td>843,775</td></tr>
            </table>
            <h2>Item 7.01 Regulation FD Disclosure</h2>
            """,
            holdings_before=847_363,
        )

        self.assertEqual(result.status, MstrBtcParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.sold_btc, 3_588)
        self.assertEqual(result.candidate.holdings_after_btc, 843_775)
        self.assertEqual(result.candidate.attributes["holdings_match_count"], 2)
        self.assertEqual(result.candidate.attributes["sold_label_count"], 2)

    def test_one_btc_holdings_discrepancy_is_tolerated_and_recorded(self) -> None:
        # June 15 reported 1,587 acquired but holdings moved by 1,586.
        result = _parse(
            """
            <h2>BTC Update</h2>
            <table>
              <tr><td>BTC Acquired</td><td>1,587</td></tr>
              <tr><td>Aggregate BTC Holdings</td><td>846,842</td></tr>
            </table>
            <h2>ATM Update</h2>
            """,
            holdings_before=845_256,
        )

        self.assertEqual(result.status, MstrBtcParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.acquired_btc, 1_587)
        self.assertEqual(
            result.candidate.holdings_crosscheck_difference_btc,
            -1,
        )

    def test_no_purchase_hyphen_is_explicit_zero_not_a_missing_value(self) -> None:
        # Mirrors July 13/20: a hyphen in the table plus a no-purchase footnote.
        result = _parse(
            """
            <h2>BTC Update</h2>
            <table>
              <tr>
                <td>BTC Acquired (1)</td>
                <td>Aggregate Purchase Price (in millions)</td>
                <td>Aggregate BTC Holdings</td>
              </tr>
              <tr><td>&mdash;</td><td>$-</td><td>843,775</td></tr>
            </table>
            <p>No bitcoin purchases were made during the period.</p>
            <h2>ATM Update</h2>
            """,
            holdings_before=843_775,
        )

        self.assertEqual(result.status, MstrBtcParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.acquired_btc, 0)
        self.assertEqual(
            result.candidate.acquired_derivation,
            MstrBtcValueDerivation.EXPLICIT,
        )
        self.assertIsNone(result.candidate.sold_btc)

    def test_narrative_holdings_supports_no_purchase_layout(self) -> None:
        # Mirrors May 26, which did not use the standard holdings table.
        result = _parse(
            """
            <h2>BTC Update</h2>
            <p>Strategy did not purchase any bitcoin during the period.</p>
            <p>As of May 24, 2026, Strategy held approximately
               843,738 bitcoins.</p>
            <h2>Item 7.01 Regulation FD Disclosure</h2>
            """,
            holdings_before=843_738,
        )

        self.assertEqual(result.status, MstrBtcParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.acquired_btc, 0)
        self.assertEqual(result.candidate.holdings_after_btc, 843_738)

    def test_holdings_only_positive_delta_is_marked_as_inferred(self) -> None:
        result = _parse(
            """
            <h2>BTC Update</h2>
            <p>Aggregate BTC Holdings 101,250</p>
            <h2>ATM Update</h2>
            """,
            holdings_before=100_000,
        )

        self.assertEqual(result.status, MstrBtcParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.acquired_btc, 1_250)
        self.assertEqual(
            result.candidate.acquired_derivation,
            MstrBtcValueDerivation.HOLDINGS_DELTA,
        )
        self.assertIsNone(result.candidate.sold_btc)

    def test_simultaneous_explicit_purchase_and_sale_are_preserved(self) -> None:
        result = _parse(
            """
            <h2>BTC Update</h2>
            <table>
              <tr><td>BTC Acquired</td><td>1,200</td></tr>
              <tr><td>BTC Sold</td><td>200</td></tr>
              <tr><td>Aggregate BTC Holdings</td><td>101,000</td></tr>
            </table>
            <h2>ATM Update</h2>
            """,
            holdings_before=100_000,
        )

        self.assertEqual(result.status, MstrBtcParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.acquired_btc, 1_200)
        self.assertEqual(result.candidate.sold_btc, 200)

    def test_malformed_operation_label_is_quarantined(self) -> None:
        result = _parse(
            """
            <h2>BTC Update</h2>
            <table>
              <tr><td>BTC Sold</td><td>not disclosed</td></tr>
              <tr><td>Aggregate BTC Holdings</td><td>99,000</td></tr>
            </table>
            <h2>ATM Update</h2>
            """,
            holdings_before=100_000,
        )

        self.assertEqual(result.status, MstrBtcParseStatus.QUARANTINED)
        self.assertEqual(result.reason, "btc_sold_value_malformed")

    def test_explicit_activity_conflicting_with_holdings_is_quarantined(self) -> None:
        result = _parse(
            """
            <h2>BTC Update</h2>
            <table>
              <tr><td>BTC Acquired</td><td>500</td></tr>
              <tr><td>BTC Sold</td><td>100</td></tr>
              <tr><td>Aggregate BTC Holdings</td><td>101,000</td></tr>
            </table>
            <h2>ATM Update</h2>
            """,
            holdings_before=100_000,
        )

        self.assertEqual(result.status, MstrBtcParseStatus.QUARANTINED)
        self.assertEqual(
            result.reason,
            "explicit_activity_conflicts_with_holdings",
        )

    def test_only_final_holdings_inside_btc_block_are_considered(self) -> None:
        result = _parse(
            """
            <h2>BTC Updates</h2>
            <p>Aggregate BTC Holdings 846,000</p>
            <p>Aggregate BTC Holdings 843,775</p>
            <h2>Item 7.01 Regulation FD Disclosure</h2>
            <p>Aggregate BTC Holdings 999,999</p>
            """,
            holdings_before=847_363,
        )

        self.assertEqual(result.status, MstrBtcParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.holdings_after_btc, 843_775)

    def test_unrelated_8k_is_no_match_not_a_negative_signal(self) -> None:
        result = _parse(
            "<h2>Item 8.01 Other Events</h2><p>Unrelated disclosure.</p>",
            holdings_before=843_775,
        )

        self.assertEqual(result.status, MstrBtcParseStatus.NO_MATCH)
        self.assertEqual(result.reason, "btc_update_block_not_found")


if __name__ == "__main__":
    unittest.main()
