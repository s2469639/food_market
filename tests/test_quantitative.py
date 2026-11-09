import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from market_compass.analysis import analyze
from market_compass.comtrade import ComtradeClient, DataError
from market_compass.__main__ import main


def envelope(year, value, **changes):
    # Synthetic arithmetic fixtures only; never displayed as market observations.
    row = dict(reporterCode=36, refYear=year, period=str(year), reporterDesc="Test country",
               cmdCode="190531", classificationCode="H6", flowCode="M", partnerCode=0,
               partner2Code=0, customsCode="C00", motCode=0, typeCode="C", freqCode="A",
               aggrLevel=6, primaryValue=value, netWgt=10, isReported=False,
               isAggregate=True, isNetWgtEstimated=False)
    row.update(changes)
    return dict(source_url="https://example.invalid/test-fixture", retrieved_at="2026-11-05T00:00:00Z",
                response=dict(count=1, error="", data=[row]))


class AnalysisTests(unittest.TestCase):
    def test_growth_and_provenance(self):
        annual, summary = analyze([envelope(2022, 100), envelope(2023, 121), envelope(2024, 144)],
                                  [36], [2022, 2023, 2024])
        self.assertAlmostEqual(summary[0]["cagr_pct"], 20)
        self.assertEqual(summary[0]["change_usd"], 44)
        self.assertAlmostEqual(annual[1]["yoy_pct"], 21)
        self.assertEqual(annual[0]["source_url"], "https://example.invalid/test-fixture")
        self.assertFalse(annual[0]["is_reported"])
        self.assertTrue(summary[0]["requires_review"])

    def test_missing_middle_never_bridged(self):
        annual, summary = analyze([envelope(2022, 100), envelope(2024, 144)], [36], [2022, 2023, 2024])
        self.assertIsNone(annual[1]["import_usd"])
        self.assertIsNone(annual[2]["yoy_pct"])
        self.assertIsNone(summary[0]["cagr_pct"])
        self.assertEqual(summary[0]["missing_years"], [2023])

    def test_zero_base(self):
        annual, summary = analyze([envelope(2022, 0), envelope(2023, 50)], [36], [2022, 2023])
        self.assertIsNone(annual[1]["yoy_pct"])
        self.assertIsNone(summary[0]["cagr_pct"])
        self.assertEqual(annual[1]["change_usd"], 50)

    def test_zero_endpoint_is_real_decline(self):
        _, summary = analyze([envelope(2022, 100), envelope(2023, 0)], [36], [2022, 2023])
        self.assertEqual(summary[0]["cagr_pct"], -100)

    def test_duplicate_rejected(self):
        data = envelope(2022, 100)
        with self.assertRaises(DataError):
            analyze([data, copy.deepcopy(data)], [36], [2022, 2023])

    def test_mismatched_scope_rejected(self):
        for changes in ({"cmdCode": "190590"}, {"partnerCode": 410}, {"classificationCode": "H5"},
                        {"flowCode": "X"}, {"reporterCode": 842}, {"period": "2021"}):
            with self.subTest(changes=changes), self.assertRaises(DataError):
                analyze([envelope(2022, 100, **changes)], [36], [2022, 2023])

    def test_invalid_values_rejected(self):
        for value in (-1, float("nan"), float("inf"), "oops", True):
            with self.subTest(value=value), self.assertRaises(DataError):
                analyze([envelope(2022, value)], [36], [2022, 2023])

    def test_no_data_remains_missing(self):
        annual, summary = analyze([], [36], [2022, 2023])
        self.assertEqual(len(annual), 2)
        self.assertFalse(summary[0]["complete"])
        self.assertEqual(summary[0]["missing_years"], [2022, 2023])

    def test_nonconsecutive_period_rejected(self):
        with self.assertRaises(DataError):
            analyze([], [36], [2022, 2024])


class ClientTests(unittest.TestCase):
    def test_cache_reuses_original_response(self):
        calls = []
        def opener(url, **kwargs):
            calls.append(url)
            return io.StringIO(json.dumps(envelope(2022, 100)["response"]))
        with tempfile.TemporaryDirectory() as directory:
            client = ComtradeClient(directory, opener=opener)
            first = client.fetch_year(2022, [36])
            second = client.fetch_year(2022, [36])
            self.assertEqual(first, second)
            self.assertEqual(len(calls), 1)
            self.assertIn("/HS?", calls[0])
            self.assertNotIn("key", calls[0].lower())

    def test_retry_after_respected(self):
        calls, waits = [], []
        def opener(url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise HTTPError(url, 429, "rate limited", {"Retry-After": "12"}, None)
            return io.StringIO(json.dumps(envelope(2022, 100)["response"]))
        with tempfile.TemporaryDirectory() as directory:
            ComtradeClient(directory, opener=opener, sleep=waits.append).fetch_year(2022, [36])
        self.assertEqual(waits, [12])
        self.assertEqual(len(calls), 2)

    def test_permanent_failure_not_cached_or_leaked(self):
        def opener(url, **kwargs):
            raise HTTPError(url, 403, "sensitive-test-marker", {}, None)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DataError) as error:
                ComtradeClient(directory, opener=opener).fetch_year(2022, [36])
            self.assertNotIn("sensitive-test-marker", str(error.exception))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_truncated_response_rejected(self):
        with self.assertRaises(DataError):
            ComtradeClient._validate(dict(count=500, error="", data=[{}] * 500))

    def test_api_error_rejected(self):
        with self.assertRaises(DataError):
            ComtradeClient._validate(dict(count=0, error="API failure", data=[]))

    def test_damaged_cache_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            def opener(url, **kwargs):
                return io.StringIO(json.dumps(envelope(2022, 100)["response"]))
            client = ComtradeClient(directory, opener=opener)
            client.fetch_year(2022, [36])
            next(Path(directory).glob("*.json")).write_text("broken", encoding="utf-8")
            with self.assertRaises(DataError):
                client.fetch_year(2022, [36])


class CommandTests(unittest.TestCase):
    def test_empty_response_fails_without_overwriting_previous_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "previous.json"
            output.write_text('{"previous": true}', encoding="utf-8")
            with patch("sys.argv", ["market_compass", "--start-year", "2022", "--end-year", "2023",
                                    "--output", str(output)]), \
                 patch.object(ComtradeClient, "fetch_year", return_value={"response": {"data": []}}), \
                 patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(main(), 1)
            self.assertEqual(json.loads(output.read_text()), {"previous": True})


if __name__ == "__main__":
    unittest.main()
