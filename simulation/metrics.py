from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from models import RoutingResult


@dataclass
class MetricsCollector:
    """Collects and summarizes simulation outcomes."""

    results: list[RoutingResult] = field(default_factory=list)

    def record(self, result: RoutingResult) -> None:
        self.results.append(result)

    def summary(self) -> dict[str, float | int]:
        if not self.results:
            return {
                "total_payments": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "error_rate": 0.0,
                "avg_score": 0.0,
            }

        total = len(self.results)
        successes = sum(1 for r in self.results if r.success)
        failures = total - successes

        return {
            "total_payments": total,
            "success_rate": round(successes / total, 4),
            "avg_latency_ms": round(mean(r.latency_ms for r in self.results), 2),
            "error_rate": round(failures / total, 4),
            "avg_score": round(mean(r.score for r in self.results), 4),
        }

    def per_bank_summary(self) -> dict[str, dict[str, float | int]]:
        grouped: dict[str, list[RoutingResult]] = {}
        for result in self.results:
            grouped.setdefault(result.chosen_bank, []).append(result)

        output: dict[str, dict[str, float | int]] = {}
        for bank, items in grouped.items():
            total = len(items)
            successes = sum(1 for item in items if item.success)
            output[bank] = {
                "routed": total,
                "success_rate": round(successes / total, 4),
                "avg_latency_ms": round(mean(i.latency_ms for i in items), 2),
            }
        return output
