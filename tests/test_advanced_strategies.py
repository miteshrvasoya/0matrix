from __future__ import annotations

import unittest

from models.payment_context import PaymentContext
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics
from strategies.contextual_bandit_router import ContextualBanditRouter
from strategies.predictive_failure_router import PredictiveFailureRouter
from strategies.thompson_sampling_router import ThompsonSamplingRouter


class TestAdvancedStrategies(unittest.TestCase):
    def setUp(self) -> None:
        self.routes = [
            RouteDefinition(name="route_a", cost=0.22, capacity=1000),
            RouteDefinition(name="route_b", cost=0.22, capacity=1000),
            RouteDefinition(name="route_c", cost=0.18, capacity=1000),
        ]
        self.context_a = PaymentContext(
            amount=640.0,
            payment_method="card",
            payer_bank="BankA",
            region="US",
            timestamp="2026-03-16T09:30:00Z",
        )
        self.context_b = PaymentContext(
            amount=80.0,
            payment_method="wallet",
            payer_bank="BankB",
            region="US",
            timestamp="2026-03-16T20:15:00Z",
        )
        self.metrics = {
            "route_a": RouteMetrics(success_rate=0.98, error_rate=0.02, avg_latency=180, sample_size=2500),
            "route_b": RouteMetrics(success_rate=0.92, error_rate=0.08, avg_latency=70, sample_size=2500),
            "route_c": RouteMetrics(success_rate=0.90, error_rate=0.10, avg_latency=110, sample_size=2500),
        }

    def test_thompson_sampling_selects_high_probability_route(self) -> None:
        router = ThompsonSamplingRouter(seed=17)
        decision = router.choose_route(self.context_a, self.routes[:2], self.metrics)
        self.assertEqual(decision.selected_route, "route_a")
        self.assertGreaterEqual(decision.confidence, 0.0)

    def test_contextual_bandit_changes_with_payment_context(self) -> None:
        router = ContextualBanditRouter(
            route_preferences={
                "route_a": ["BankA"],
                "route_b": ["BankB"],
            },
            bank_affinity_bonus=0.18,
        )
        tied_metrics = {
            "route_a": RouteMetrics(success_rate=0.95, error_rate=0.05, avg_latency=120, sample_size=1200),
            "route_b": RouteMetrics(success_rate=0.95, error_rate=0.05, avg_latency=120, sample_size=1200),
        }

        decision_a = router.choose_route(self.context_a, self.routes[:2], tied_metrics)
        decision_b = router.choose_route(self.context_b, self.routes[:2], tied_metrics)

        self.assertEqual(decision_a.selected_route, "route_a")
        self.assertEqual(decision_b.selected_route, "route_b")

    def test_predictive_failure_router_avoids_degrading_route(self) -> None:
        router = PredictiveFailureRouter(history_window=8)
        initial_decision = router.choose_route(self.context_a, self.routes[:2], self.metrics)
        self.assertEqual(initial_decision.selected_route, "route_a")

        for latency_ms in (180.0, 210.0, 260.0, 340.0):
            router.record_outcome("route_a", success=False, latency_ms=latency_ms)
        for latency_ms in (95.0, 100.0, 105.0, 110.0):
            router.record_outcome("route_b", success=True, latency_ms=latency_ms)

        degraded_decision = router.choose_route(self.context_a, self.routes[:2], self.metrics)
        self.assertEqual(degraded_decision.selected_route, "route_b")

    def test_metric_changes_shift_contextual_reward(self) -> None:
        router = ContextualBanditRouter(
            route_preferences={
                "route_a": ["BankA"],
                "route_b": ["BankB"],
            },
            bank_affinity_bonus=0.05,
        )
        healthy_metrics = {
            "route_a": RouteMetrics(success_rate=0.97, error_rate=0.03, avg_latency=90, sample_size=900),
            "route_b": RouteMetrics(success_rate=0.92, error_rate=0.08, avg_latency=120, sample_size=900),
        }
        degraded_metrics = {
            "route_a": RouteMetrics(success_rate=0.82, error_rate=0.18, avg_latency=190, sample_size=900),
            "route_b": RouteMetrics(success_rate=0.96, error_rate=0.04, avg_latency=95, sample_size=900),
        }

        decision_healthy = router.choose_route(self.context_a, self.routes[:2], healthy_metrics)
        decision_degraded = router.choose_route(self.context_a, self.routes[:2], degraded_metrics)

        self.assertEqual(decision_healthy.selected_route, "route_a")
        self.assertEqual(decision_degraded.selected_route, "route_b")

    def test_advanced_strategies_behave_differently(self) -> None:
        thompson = ThompsonSamplingRouter(seed=17)
        contextual = ContextualBanditRouter(
            route_preferences={"route_b": ["BankB"]},
            bank_affinity_bonus=0.20,
        )
        predictive = PredictiveFailureRouter(history_window=8)

        for latency_ms in (170.0, 220.0, 280.0, 360.0):
            predictive.record_outcome("route_a", success=False, latency_ms=latency_ms)

        thompson_decision = thompson.choose_route(self.context_b, self.routes[:2], self.metrics)
        contextual_decision = contextual.choose_route(self.context_b, self.routes[:2], self.metrics)
        predictive_decision = predictive.choose_route(self.context_b, self.routes[:2], self.metrics)

        selected_routes = {
            thompson_decision.selected_route,
            contextual_decision.selected_route,
            predictive_decision.selected_route,
        }
        self.assertGreaterEqual(len(selected_routes), 2)


if __name__ == "__main__":
    unittest.main()
