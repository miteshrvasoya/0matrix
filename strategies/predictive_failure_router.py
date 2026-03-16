from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import mean, pvariance
from typing import Mapping

from core.base_strategy import BaseRoutingStrategy
from models.payment_context import PaymentContext
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics
from models.routing_decision import RoutingDecision


@dataclass
class _RouteHealthHistory:
    latencies: deque[float] = field(default_factory=lambda: deque(maxlen=20))
    errors: deque[float] = field(default_factory=lambda: deque(maxlen=20))


class PredictiveFailureRouter(BaseRoutingStrategy):
    """Avoids degrading routes by penalizing early signs of instability."""

    def __init__(
        self,
        latency_trend_weight: float = 0.40,
        error_trend_weight: float = 0.35,
        instability_weight: float = 0.25,
        latency_penalty_weight: float = 0.15,
        max_latency_ms: float = 2000.0,
        history_window: int = 20,
    ) -> None:
        if max_latency_ms <= 0.0:
            raise ValueError("max_latency_ms must be > 0")
        if history_window < 4:
            raise ValueError("history_window must be >= 4")
        if latency_penalty_weight < 0.0:
            raise ValueError("latency_penalty_weight must be >= 0")

        total = latency_trend_weight + error_trend_weight + instability_weight
        if total <= 0.0:
            raise ValueError("risk weights must total > 0")

        self.latency_trend_weight = latency_trend_weight / total
        self.error_trend_weight = error_trend_weight / total
        self.instability_weight = instability_weight / total
        self.latency_penalty_weight = latency_penalty_weight
        self.max_latency_ms = max_latency_ms
        self.history_window = history_window
        self._history: dict[str, _RouteHealthHistory] = {}

    def choose_route(
        self,
        context: PaymentContext,
        routes: list[RouteDefinition],
        metrics: Mapping[str, RouteMetrics] | None,
    ) -> RoutingDecision:
        del context
        available = sorted((route for route in routes if route.capacity > 0), key=lambda item: item.name)
        if not available:
            raise ValueError("no routes with positive capacity")

        metric_map = metrics or {}
        scored: list[tuple[str, float]] = []
        risk_by_route: dict[str, float] = {}
        for route in available:
            route_metrics = self._resolve_metrics(route.name, metric_map)
            risk_score = self.calculate_risk(route.name, route_metrics)
            latency_penalty = self.latency_penalty_weight * _clamp(
                route_metrics.avg_latency / self.max_latency_ms
            )
            score = _clamp(route_metrics.success_rate) - latency_penalty - risk_score
            scored.append((route.name, score))
            risk_by_route[route.name] = risk_score

        scored.sort(key=lambda item: (-item[1], item[0]))
        selected_route, selected_score = scored[0]
        confidence = _confidence_from_margin(scored, risk_by_route[selected_route])
        return RoutingDecision(
            selected_route=selected_route,
            score=round(selected_score, 6),
            confidence=round(confidence, 6),
        )

    def calculate_risk(self, route_name: str, route_metrics: RouteMetrics) -> float:
        history = self._history.setdefault(
            route_name,
            _RouteHealthHistory(
                latencies=deque(maxlen=self.history_window),
                errors=deque(maxlen=self.history_window),
            ),
        )
        latency_growth = self._latency_growth(history, route_metrics)
        error_spike = self._error_spike(history, route_metrics)
        latency_variance = self._latency_variance(history)
        return _clamp(
            (self.latency_trend_weight * latency_growth)
            + (self.error_trend_weight * error_spike)
            + (self.instability_weight * latency_variance)
        )

    def record_outcome(
        self,
        route_name: str,
        success: bool,
        latency_ms: float,
        cost: float | None = None,
    ) -> None:
        del cost
        history = self._history.setdefault(
            route_name,
            _RouteHealthHistory(
                latencies=deque(maxlen=self.history_window),
                errors=deque(maxlen=self.history_window),
            ),
        )
        history.latencies.append(latency_ms)
        history.errors.append(0.0 if success else 1.0)

    def snapshot_state(self) -> dict:
        return {
            "history": {
                route_name: {
                    "latencies": list(history.latencies),
                    "errors": list(history.errors),
                }
                for route_name, history in self._history.items()
            }
        }

    def restore_state(self, state: dict) -> None:
        restored: dict[str, _RouteHealthHistory] = {}
        for route_name, raw in state.get("history", {}).items():
            restored[route_name] = _RouteHealthHistory(
                latencies=deque(
                    (float(value) for value in raw.get("latencies", [])),
                    maxlen=self.history_window,
                ),
                errors=deque(
                    (float(value) for value in raw.get("errors", [])),
                    maxlen=self.history_window,
                ),
            )
        self._history = restored

    def _resolve_metrics(
        self,
        route_name: str,
        metrics: Mapping[str, RouteMetrics],
    ) -> RouteMetrics:
        if route_name in metrics:
            return metrics[route_name]

        history = self._history.get(route_name)
        if history and history.latencies and history.errors:
            avg_latency = mean(history.latencies)
            error_rate = mean(history.errors)
            success_rate = 1.0 - error_rate
            return RouteMetrics(
                success_rate=success_rate,
                error_rate=error_rate,
                avg_latency=avg_latency,
                sample_size=len(history.errors),
            )

        return RouteMetrics(success_rate=0.5, error_rate=0.5, avg_latency=1000.0, sample_size=0)

    @staticmethod
    def _latency_growth(history: _RouteHealthHistory, route_metrics: RouteMetrics) -> float:
        if len(history.latencies) >= 4:
            midpoint = len(history.latencies) // 2
            earlier = list(history.latencies)[:midpoint]
            recent = list(history.latencies)[midpoint:]
            baseline = max(mean(earlier), 1.0)
            return _clamp(max(0.0, mean(recent) - baseline) / baseline)
        if history.latencies:
            baseline = max(mean(history.latencies), 1.0)
            return _clamp(max(0.0, route_metrics.avg_latency - baseline) / baseline)
        return _clamp(route_metrics.avg_latency / 4000.0)

    @staticmethod
    def _error_spike(history: _RouteHealthHistory, route_metrics: RouteMetrics) -> float:
        if len(history.errors) >= 4:
            midpoint = len(history.errors) // 2
            earlier = list(history.errors)[:midpoint]
            recent = list(history.errors)[midpoint:]
            baseline = mean(earlier)
            recent_rate = mean(recent)
            spike = max(0.0, recent_rate - baseline)
            return _clamp(max(route_metrics.error_rate, recent_rate) + spike)
        if history.errors:
            return _clamp(max(route_metrics.error_rate, mean(history.errors)))
        return _clamp(route_metrics.error_rate)

    def _latency_variance(self, history: _RouteHealthHistory) -> float:
        if len(history.latencies) < 2:
            return 0.0
        variance = pvariance(history.latencies)
        return _clamp((variance ** 0.5) / self.max_latency_ms)


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _confidence_from_margin(scored: list[tuple[str, float]], selected_risk: float) -> float:
    if len(scored) == 1:
        return 1.0 - (selected_risk / 2.0)
    margin = _clamp(scored[0][1] - scored[1][1])
    stability = 1.0 - (selected_risk / 2.0)
    return _clamp((margin + stability) / 2.0)
