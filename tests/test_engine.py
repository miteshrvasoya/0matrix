from __future__ import annotations

import unittest
from unittest.mock import patch

import strategies  # noqa: F401
from core.base_strategy import BaseRoutingStrategy
from core.router_engine import RouterEngine
from core.strategy_registry import StrategyRegistry
from models.payment_context import PaymentContext
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics
from models.routing_decision import RoutingDecision


class _EchoStrategy(BaseRoutingStrategy):
    def __init__(self) -> None:
        self.last_record: tuple[str, bool, float, float | None] | None = None

    def choose_route(self, context, routes, metrics):  # type: ignore[override]
        del context, metrics
        return RoutingDecision(selected_route=routes[0].name, score=0.55, confidence=0.88)

    def record_outcome(self, route_name, success, latency_ms, cost=None):  # type: ignore[override]
        self.last_record = (route_name, success, latency_ms, cost)

    def snapshot_state(self):
        return {"last_record": self.last_record}

    def restore_state(self, state):
        self.last_record = state.get("last_record")


class _BadStrategy(BaseRoutingStrategy):
    def choose_route(self, context, routes, metrics):  # type: ignore[override]
        del context, routes, metrics
        return RoutingDecision(selected_route="bad", score=0.1, confidence=1.2)

    def record_outcome(self, route_name, success, latency_ms, cost=None):  # type: ignore[override]
        del route_name, success, latency_ms, cost

    def snapshot_state(self):
        return {}

    def restore_state(self, state):
        del state


class TestRouterEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.context = PaymentContext(
            amount=100.0,
            payment_method="card",
            payer_bank="BankA",
            region="US",
            timestamp="2026-03-07T00:00:00Z",
        )
        self.routes = [
            RouteDefinition(name="route_a", cost=0.1, capacity=10),
            RouteDefinition(name="route_b", cost=0.2, capacity=10),
        ]
        self.metrics = {
            "route_a": RouteMetrics(success_rate=0.8, error_rate=0.2, avg_latency=100, sample_size=10),
            "route_b": RouteMetrics(success_rate=0.9, error_rate=0.1, avg_latency=90, sample_size=10),
        }

    def test_engine_delegates_route_decision(self) -> None:
        engine = RouterEngine(strategy=_EchoStrategy())
        decision = engine.route(self.context, self.routes, self.metrics)
        self.assertEqual(decision.selected_route, "route_a")
        self.assertAlmostEqual(decision.confidence, 0.88)

    def test_engine_outcome_feedback_roundtrip(self) -> None:
        strategy = _EchoStrategy()
        engine = RouterEngine(strategy=strategy)
        engine.record_outcome("route_a", True, 87.2, 0.21)
        self.assertEqual(strategy.last_record, ("route_a", True, 87.2, 0.21))

    def test_engine_rejects_invalid_confidence(self) -> None:
        engine = RouterEngine(strategy=_BadStrategy())
        with self.assertRaises(ValueError):
            engine.route(self.context, self.routes, self.metrics)

    def test_engine_accepts_registered_strategy_name(self) -> None:
        engine = RouterEngine(strategy="thompson")
        decision = engine.route(self.context, self.routes, self.metrics)
        self.assertIn(decision.selected_route, {"route_a", "route_b"})
        self.assertGreaterEqual(decision.confidence, 0.0)

    def test_engine_from_registry(self) -> None:
        engine = RouterEngine.from_registry("weighted")
        decision = engine.route(self.context, self.routes, self.metrics)
        self.assertIn(decision.selected_route, {"route_a", "route_b"})
        self.assertGreaterEqual(decision.confidence, 0.0)

    def test_registry_autodiscover_calls_entrypoint_loader(self) -> None:
        class _PluginStrategy(_EchoStrategy):
            pass

        class _EntryPoint:
            name = "plugin_weighted"

            @staticmethod
            def load():
                return _PluginStrategy

        with patch.object(StrategyRegistry, "_select_entry_points", return_value=[_EntryPoint()]):
            StrategyRegistry.autodiscover(entrypoint_group="smart_router.strategies")

        engine = RouterEngine.from_registry("plugin_weighted")
        decision = engine.route(self.context, self.routes, self.metrics)
        self.assertEqual(decision.selected_route, "route_a")


if __name__ == "__main__":
    unittest.main()
