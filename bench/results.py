"""Shared result and summary-stats shapes."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any


def _summary_stats(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    n = len(ordered)
    pick = lambda q: ordered[int(q * (n - 1))] if n else 0.0
    return {
        "count": n,
        "mean_ms": round(statistics.mean(samples), 3) if n else 0.0,
        "median_ms": round(statistics.median(samples), 3) if n else 0.0,
        "p50_ms": round(pick(0.50), 3),
        "p95_ms": round(pick(0.95), 3),
        "p99_ms": round(pick(0.99), 3),
        "min_ms": round(min(samples), 3) if n else 0.0,
        "max_ms": round(max(samples), 3) if n else 0.0,
    }


@dataclass
class MeshResult:
    name: str
    samples: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {"scenario": self.name}
        out.update(_summary_stats(self.samples))
        out["metadata"] = self.metadata
        return out
