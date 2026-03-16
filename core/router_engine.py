from __future__ import annotations

from typing import Mapping

from core.base_strategy import BaseRoutingStrategy
from core.strategy_registry import StrategyRegistry
from models.payment_context import PaymentContext
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics
from models.routing_decision import RoutingDecision


class RouterEngine:
    """Executes a routing strategy and exposes a stable host integration contract."""

    def __init__(
        self,
        strategy: BaseRoutingStrategy | str,
        config: dict | None = None,
    ) -> None:
        self._strategy = self._resolve_strategy(strategy=strategy, config=config)

    @classmethod
    def from_registry(cls, strategy_name: str, config: dict | None = None) -> "RouterEngine":
        return cls(strategy=strategy_name, config=config)

    def route(
        self,
        context: PaymentContext,
        routes: list[RouteDefinition],
        metrics: Mapping[str, RouteMetrics] | None = None,
    ) -> RoutingDecision:
        if not routes:
            raise ValueError("routes must not be empty")
        decision = self._strategy.choose_route(context=context, routes=routes, metrics=metrics or {})
        if decision.confidence < 0.0 or decision.confidence > 1.0:
            raise ValueError("strategy returned invalid confidence outside [0, 1]")
        return decision

    def record_outcome(
        self,
        route_name: str,
        success: bool,
        latency_ms: float,
        cost: float | None = None,
    ) -> None:
        self._strategy.record_outcome(
            route_name=route_name, success=success, latency_ms=latency_ms, cost=cost
        )

    def snapshot_state(self) -> dict:
        return self._strategy.snapshot_state()

    def restore_state(self, state: dict) -> None:
        self._strategy.restore_state(state)

    @staticmethod
    def _resolve_strategy(
        strategy: BaseRoutingStrategy | str,
        config: dict | None,
    ) -> BaseRoutingStrategy:
        if isinstance(strategy, BaseRoutingStrategy):
            return strategy
        if isinstance(strategy, str):
            import strategies  # noqa: F401

            return StrategyRegistry.create(strategy, config or {})
        raise TypeError("strategy must be a BaseRoutingStrategy instance or registered name")
