from __future__ import annotations

import unittest

from models.payment_context import PaymentContext
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics
from strategies.epsilon_bandit_router import EpsilonBanditRouter
from strategies.thompson_sampling_router import ThompsonSamplingRouter
from strategies.weighted_router import WeightedRouter


class TestStrategies(unittest.TestCase):
    def setUp(self) -> None:
        self.context = PaymentContext(
            amount=250.0,
            payment_method="card",
            payer_bank=None,
            region="EU",
            timestamp="2026-03-07T00:00:00Z",
        )
        self.routes = [
            RouteDefinition(name="route_a", cost=0.30, capacity=1000),
            RouteDefinition(name="route_b", cost=0.12, capacity=1000),
            RouteDefinition(name="route_c", cost=0.25, capacity=1000),
        ]
        self.metrics = {
            "route_a": RouteMetrics(success_rate=0.95, error_rate=0.05, avg_latency=190, sample_size=1000),
            "route_b": RouteMetrics(success_rate=0.93, error_rate=0.07, avg_latency=90, sample_size=1000),
            "route_c": RouteMetrics(success_rate=0.90, error_rate=0.10, avg_latency=240, sample_size=1000),
        }

    def test_weighted_router_selects_expected_route(self) -> None:
        router = WeightedRouter()
        decision = router.choose_route(self.context, self.routes, self.metrics)
        self.assertEqual(decision.selected_route, "route_b")
        self.assertGreater(decision.score, 0.0)
        self.assertGreaterEqual(decision.confidence, 0.0)

    def test_weighted_router_tie_breaks_by_name(self) -> None:
        router = WeightedRouter(success_weight=1.0, latency_weight=0.0, cost_weight=0.0, error_weight=0.0)
        tied_metrics = {
            "route_a": RouteMetrics(success_rate=0.9, error_rate=0.1, avg_latency=100, sample_size=10),
            "route_b": RouteMetrics(success_rate=0.9, error_rate=0.1, avg_latency=100, sample_size=10),
        }
        decision = router.choose_route(self.context, self.routes[:2], tied_metrics)
        self.assertEqual(decision.selected_route, "route_a")

    def test_weighted_router_rejects_no_capacity(self) -> None:
        router = WeightedRouter()
        routes = [RouteDefinition(name="disabled", cost=0.2, capacity=0)]
        with self.assertRaises(ValueError):
            router.choose_route(self.context, routes, self.metrics)

    def test_epsilon_bandit_cold_start(self) -> None:
        router = EpsilonBanditRouter(epsilon=0.1, seed=11)
        decision = router.choose_route(self.context, self.routes, self.metrics)
        self.assertEqual(decision.selected_route, "route_a")
        self.assertGreaterEqual(decision.confidence, 0.0)

    def test_epsilon_bandit_exploits_after_feedback(self) -> None:
        router = EpsilonBanditRouter(epsilon=0.0, seed=7)
        router.record_outcome("route_a", False, 1600.0)
        router.record_outcome("route_a", False, 1400.0)
        router.record_outcome("route_b", True, 120.0)
        router.record_outcome("route_b", True, 110.0)
        decision = router.choose_route(self.context, self.routes[:2], self.metrics)
        self.assertEqual(decision.selected_route, "route_b")

    def test_thompson_posterior_updates(self) -> None:
        router = ThompsonSamplingRouter(seed=9)
        router.record_outcome("route_a", True, 120.0)
        router.record_outcome("route_a", False, 200.0)
        state = router.snapshot_state()
        route_state = state["state"]["route_a"]
        self.assertEqual(route_state["observations"], 2)
        self.assertEqual(route_state["successes"], 1)
        self.assertEqual(route_state["failures"], 1)

    def test_thompson_uses_metric_counts(self) -> None:
        router = ThompsonSamplingRouter(seed=5)
        decision = router.choose_route(self.context, self.routes, self.metrics)
        self.assertEqual(decision.selected_route, "route_a")
        self.assertGreaterEqual(decision.confidence, 0.0)

    def test_missing_metrics_uses_neutral_defaults(self) -> None:
        router = WeightedRouter()
        decision = router.choose_route(self.context, self.routes, {})
        self.assertIn(decision.selected_route, {"route_a", "route_b", "route_c"})


if __name__ == "__main__":
    unittest.main()
