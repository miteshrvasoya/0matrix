from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from core.base_strategy import BaseRoutingStrategy
from models.payment_context import PaymentContext
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics
from models.routing_decision import RoutingDecision


@dataclass
class _FeedbackStats:
    observations: int = 0
    successes: int = 0
    avg_latency: float = 1000.0


class WeightedRouter(BaseRoutingStrategy):
    """Deterministic weighted router with route-level feedback fallback."""

    def __init__(
        self,
        success_weight: float = 0.40,
        latency_weight: float = 0.25,
        cost_weight: float = 0.20,
        error_weight: float = 0.15,
        max_latency_ms: float = 2000.0,
        max_cost: float = 5.0,
    ) -> None:
        if max_latency_ms <= 0:
            raise ValueError("max_latency_ms must be > 0")
        if max_cost <= 0:
            raise ValueError("max_cost must be > 0")

        total = success_weight + latency_weight + cost_weight + error_weight
        if total <= 0:
            raise ValueError("at least one weight must be > 0")

        self.success_weight = success_weight / total
        self.latency_weight = latency_weight / total
        self.cost_weight = cost_weight / total
        self.error_weight = error_weight / total
        self.max_latency_ms = max_latency_ms
        self.max_cost = max_cost
        self._feedback: dict[str, _FeedbackStats] = {}

    def choose_route(
        self,
        context: PaymentContext,
        routes: list[RouteDefinition],
        metrics: Mapping[str, RouteMetrics] | None,
    ) -> RoutingDecision:
        del context
        available = sorted((r for r in routes if r.capacity > 0), key=lambda route: route.name)
        if not available:
            raise ValueError("no routes with positive capacity")

        metric_map = metrics or {}
        scored: list[tuple[RouteDefinition, float]] = []
        for route in available:
            route_metrics = self._resolve_metrics(route.name, metric_map)
            score = self._score(route, route_metrics)
            scored.append((route, score))

        scored.sort(key=lambda item: (-item[1], item[0].name))
        best_route, best_score = scored[0]
        confidence = self._weighted_confidence(scored)
        return RoutingDecision(
            selected_route=best_route.name,
            score=round(best_score, 6),
            confidence=round(confidence, 6),
        )

    def record_outcome(
        self,
        route_name: str,
        success: bool,
        latency_ms: float,
        cost: float | None = None,
    ) -> None:
        del cost
        stats = self._feedback.setdefault(route_name, _FeedbackStats())
        stats.observations += 1
        if success:
            stats.successes += 1
        stats.avg_latency += (latency_ms - stats.avg_latency) / stats.observations

    def snapshot_state(self) -> dict:
        return {
            "feedback": {
                route: {
                    "observations": stats.observations,
                    "successes": stats.successes,
                    "avg_latency": stats.avg_latency,
                }
                for route, stats in self._feedback.items()
            }
        }

    def restore_state(self, state: dict) -> None:
        feedback = state.get("feedback", {})
        restored: dict[str, _FeedbackStats] = {}
        for route_name, raw in feedback.items():
            restored[route_name] = _FeedbackStats(
                observations=int(raw.get("observations", 0)),
                successes=int(raw.get("successes", 0)),
                avg_latency=float(raw.get("avg_latency", 1000.0)),
            )
        self._feedback = restored

    def _resolve_metrics(
        self, route_name: str, metrics: Mapping[str, RouteMetrics]
    ) -> RouteMetrics:
        if route_name in metrics:
            return metrics[route_name]

        observed = self._feedback.get(route_name)
        if observed and observed.observations > 0:
            success_rate = observed.successes / observed.observations
            return RouteMetrics(
                success_rate=success_rate,
                error_rate=1.0 - success_rate,
                avg_latency=observed.avg_latency,
                sample_size=observed.observations,
            )

        return RouteMetrics(success_rate=0.5, error_rate=0.5, avg_latency=1000.0, sample_size=0)

    def _score(self, route: RouteDefinition, route_metrics: RouteMetrics) -> float:
        success = _clamp(route_metrics.success_rate)
        error_inverse = 1.0 - _clamp(route_metrics.error_rate)
        latency_inverse = 1.0 - _clamp(route_metrics.avg_latency / self.max_latency_ms)
        cost_inverse = 1.0 - _clamp(route.cost / self.max_cost)

        return (
            (self.success_weight * success)
            + (self.latency_weight * latency_inverse)
            + (self.cost_weight * cost_inverse)
            + (self.error_weight * error_inverse)
        )

    @staticmethod
    def _weighted_confidence(scored: list[tuple[RouteDefinition, float]]) -> float:
        if len(scored) == 1:
            return 1.0
        margin = scored[0][1] - scored[1][1]
        return _clamp(margin)


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))
