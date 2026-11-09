import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from market_compass.api import create_app
from market_compass.comparison import FIXTURE, build_comparison
from market_compass.storage import RunStore


class ComparisonTests(unittest.TestCase):
    def test_reviewed_data_recalculated_without_network(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("No network allowed")):
            result = build_comparison()
        self.assertEqual(result["product"]["version"], "P01-public-label-v1")
        self.assertEqual([c["reporter_code"] for c in result["countries"]], [36, 392])
        australia, japan = result["countries"]
        self.assertEqual(len(australia["annual"]), 3)
        self.assertAlmostEqual(australia["quantitative"]["cagr_pct"], 10.423427, places=5)
        self.assertAlmostEqual(japan["quantitative"]["cagr_pct"], 31.059509, places=5)
        self.assertIn("품목 범위", japan["scope_warning"])
        self.assertEqual(japan["status"], "추가 검증")
        source_ids = {e["id"] for e in result["evidence"]}
        for country in result["countries"]:
            self.assertTrue(set(country["signal_sources"]) <= source_ids)
            self.assertTrue(all(row["source_url"] and row["retrieved_at"] for row in country["annual"]))

    def test_snapshot_survives_new_store_and_changed_fixture(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runs.sqlite3"
            comparison = build_comparison()
            saved = RunStore(path).save(comparison)
            comparison["product"]["name"] = "changed later"
            restored = RunStore(path).get(saved["id"])
            self.assertEqual(restored, saved)
            self.assertEqual(RunStore(path).list()[0]["product_version"], "P01-public-label-v1")
            self.assertIsNone(RunStore(path).get("' OR 1=1 --"))

    def test_invalid_fixture_does_not_save_partial_result(self):
        with TemporaryDirectory() as directory:
            fixture = json.loads(FIXTURE.read_text())
            fixture["envelopes"][0]["response"]["data"][0]["classificationCode"] = "H5"
            bad = Path(directory) / "bad.json"
            bad.write_text(json.dumps(fixture))
            client = TestClient(create_app(Path(directory) / "runs.sqlite3"))
            with patch("market_compass.comparison.FIXTURE", bad):
                self.assertEqual(client.post("/api/runs").status_code, 422)
            self.assertEqual(client.get("/api/runs").json(), [])

    def test_api_roundtrip_and_cross_site_write_rejection(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runs.sqlite3"
            client = TestClient(create_app(path))
            self.assertEqual(client.post("/api/runs", headers={"origin": "https://unrelated.example"}).status_code, 403)
            self.assertEqual(client.get("/api/runs").json(), [])
            response = client.post("/api/runs", headers={"origin": "http://127.0.0.1:8000"})
            self.assertEqual(response.status_code, 201)
            run = response.json()
            another = TestClient(create_app(path))
            self.assertEqual(another.get(f"/api/runs/{run['id']}").json(), run)
            self.assertEqual(len(another.get("/api/runs").json()), 1)
            self.assertEqual(another.get("/api/runs/not-an-id").status_code, 422)
            self.assertEqual(another.get("/api/runs/00000000-0000-0000-0000-000000000000").status_code, 404)


if __name__ == "__main__":
    unittest.main()
