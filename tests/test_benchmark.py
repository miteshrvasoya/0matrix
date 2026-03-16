from __future__ import annotations

import unittest

from benchmark.performance_report import build_report
from benchmark.strategy_benchmark import StrategyBenchmarkRunner
from benchmark.traffic_simulator import TrafficSimulator
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics
from strategies.contextual_bandit_router import ContextualBanditRouter
from strategies.epsilon_bandit_router import EpsilonBanditRouter
from strategies.predictive_failure_router import PredictiveFailureRouter
from strategies.thompson_sampling_router import ThompsonSamplingRouter
from strategies.weighted_router import WeightedRouter


class TestBenchmarkSmoke(unittest.TestCase):
    def test_benchmark_runner_produces_report(self) -> None:
        routes = [
            RouteDefinition(name="route_a", cost=0.25, capacity=1000),
            RouteDefinition(name="route_b", cost=0.18, capacity=1000),
        ]
        baseline = {
            "route_a": RouteMetrics(
                success_rate=0.95,
                error_rate=0.05,
                avg_latency=160,
                sample_size=500,
            ),
            "route_b": RouteMetrics(
                success_rate=0.92,
                error_rate=0.08,
                avg_latency=90,
                sample_size=500,
            ),
        }
        simulator = TrafficSimulator(route_truth=baseline, seed=7)
        runner = StrategyBenchmarkRunner(
            routes=routes,
            baseline_metrics=baseline,
            simulator=simulator,
        )

        results = runner.run(
            strategies={
                "weighted": WeightedRouter(),
                "bandit": EpsilonBanditRouter(seed=7),
                "thompson": ThompsonSamplingRouter(seed=7),
                "contextual_bandit": ContextualBanditRouter(),
                "predictive_failure": PredictiveFailureRouter(),
            },
            transactions=200,
        )
        report = build_report(results)
        payload = report.to_dict()

        self.assertEqual(len(results), 5)
        self.assertEqual(len(payload["runs"]), 5)
        self.assertTrue(all("strategy" in row for row in payload["runs"]))


if __name__ == "__main__":
    unittest.main()
