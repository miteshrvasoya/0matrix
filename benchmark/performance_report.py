from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from benchmark.strategy_benchmark import StrategyBenchmarkResult


@dataclass(frozen=True)
class StrategyRunStats:
    strategy: str
    success_rate: float
    avg_latency_ms: float
    avg_cost: float
    cost_impact_vs_cheapest: float
    transactions: int


@dataclass(frozen=True)
class BenchmarkReport:
    runs: list[StrategyRunStats]

    def to_dict(self) -> dict:
        return {"runs": [asdict(run) for run in self.runs]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def write_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.write_text(self.to_json(), encoding="utf-8")
        return target

    def print_console(self) -> None:
        print("Strategy                 Success    AvgLatency(ms)    AvgCost    CostImpact")
        print("-" * 76)
        for run in self.runs:
            print(
                f"{run.strategy:<24} "
                f"{run.success_rate:>7.2%} "
                f"{run.avg_latency_ms:>16.2f} "
                f"{run.avg_cost:>10.4f} "
                f"{run.cost_impact_vs_cheapest:>11.3f}x"
            )


def build_report(results: list[StrategyBenchmarkResult]) -> BenchmarkReport:
    runs = [
        StrategyRunStats(
            strategy=result.strategy_name,
            success_rate=result.success_rate,
            avg_latency_ms=result.avg_latency_ms,
            avg_cost=result.avg_cost,
            cost_impact_vs_cheapest=result.cost_impact_vs_cheapest,
            transactions=result.transactions,
        )
        for result in results
    ]
    return BenchmarkReport(runs=runs)
