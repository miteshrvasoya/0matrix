from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping

from models.payment_context import PaymentContext
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics
from models.routing_decision import RoutingDecision


class BaseRoutingStrategy(ABC):
    """Base contract for all routing strategy plugins."""

    @abstractmethod
    def choose_route(
        self,
        context: PaymentContext,
        routes: list[RouteDefinition],
        metrics: Mapping[str, RouteMetrics] | None,
    ) -> RoutingDecision:
        """Select the best route for a payment context."""

    @abstractmethod
    def record_outcome(
        self,
        route_name: str,
        success: bool,
        latency_ms: float,
        cost: float | None = None,
    ) -> None:
        """Consume route execution outcome feedback from the host application."""

    @abstractmethod
    def snapshot_state(self) -> dict:
        """Return serializable strategy state for host-managed persistence."""

    @abstractmethod
    def restore_state(self, state: dict) -> None:
        """Restore strategy state previously emitted by ``snapshot_state``."""
