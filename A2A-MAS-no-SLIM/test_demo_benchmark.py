"""Tests for demo benchmark scenarios."""
from __future__ import annotations

import asyncio
import unittest

from demo_benchmark import run_demo


class DemoBenchmarkTests(unittest.TestCase):
    def test_run_demo_returns_all_scenarios(self) -> None:
        result = asyncio.run(run_demo(rounds=5, base_port=8300, payload_size=32))
        self.assertIn("results", result)
        self.assertEqual(len(result["results"]), 3)

        names = {item["scenario"] for item in result["results"]}
        self.assertIn("fanout_http_A_to_BCDE", names)
        self.assertIn("fanout_slim_A_to_BCDE", names)
        self.assertIn("encryption_overhead_slim", names)

    def test_scenarios_have_samples(self) -> None:
        result = asyncio.run(run_demo(rounds=3, base_port=8400, payload_size=16))
        for scenario in result["results"]:
            self.assertGreaterEqual(scenario["count"], 3)
            self.assertGreaterEqual(scenario["max_ms"], scenario["min_ms"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
