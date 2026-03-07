from __future__ import annotations

from dataclasses import dataclass, replace

from models import PaymentContext, Route
from routing.bandit_router import EpsilonGreedyBanditRouter
from routing.circuit_breaker import CircuitBreaker
from routing.metrics_store import MetricsStore
from routing.route_health import HealthState, RouteHealthMonitor
from routing.scoring import ScoringAlgorithm


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    score: float


class RoutingEngine:
    """Ranks and selects available routes using static or adaptive routing."""

    def __init__(
        self,
        routes: list[Route],
        scoring: ScoringAlgorithm | None = None,
        adaptive_routing_enabled: bool = False,
        bandit_router: EpsilonGreedyBanditRouter | None = None,
        metrics_store: MetricsStore | None = None,
        health_monitor: RouteHealthMonitor | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        if not routes:
            raise ValueError("At least one route is required")

        self.routes = routes
        self.scoring = scoring or ScoringAlgorithm()
        self.adaptive_routing_enabled = adaptive_routing_enabled
        self.bandit_router = bandit_router or EpsilonGreedyBanditRouter(
            route_ids=[route.route_id for route in routes]
        )
        self.metrics_store = metrics_store
        self.health_monitor = health_monitor
        self.circuit_breaker = circuit_breaker

    def choose_route(self, ctx: PaymentContext) -> RouteDecision:
        return self.rank_routes(ctx)[0]

    def rank_routes(self, ctx: PaymentContext) -> list[RouteDecision]:
        eligible = [r for r in self.routes if r.supports(ctx.currency, ctx.country)]
        if not eligible:
            raise ValueError(
                f"No eligible routes for currency={ctx.currency} country={ctx.country}"
            )

        available = [route for route in eligible if self._is_route_available(route)]
        if not available:
            raise ValueError(
                f"No available routes for currency={ctx.currency} country={ctx.country}"
            )

        if self.adaptive_routing_enabled:
            available_ids = [route.route_id for route in available]
            selected_route_id = self.bandit_router.choose_route(available_ids)
            route_by_id = {route.route_id: route for route in available}

            remaining_ids = [route_id for route_id in available_ids if route_id != selected_route_id]
            remaining_ids.sort(
                key=lambda route_id: self.bandit_router.estimated_reward(route_id),
                reverse=True,
            )

            ordered_ids = [selected_route_id, *remaining_ids]
            return [
                RouteDecision(
                    route=route_by_id[route_id],
                    score=self.bandit_router.estimated_reward(route_id),
                )
                for route_id in ordered_ids
            ]

        scored = [
            RouteDecision(
                route=route,
                score=self.scoring.score(self._effective_route(route), ctx),
            )
            for route in available
        ]
        return sorted(scored, key=lambda item: item.score, reverse=True)

    def record_attempt(self, route_id: str, success: bool, latency_ms: float) -> None:
        if not self.adaptive_routing_enabled:
            return
        self.bandit_router.update(route_id=route_id, success=success, latency_ms=latency_ms)

    def _is_route_available(self, route: Route) -> bool:
        if self.health_monitor:
            state = self.health_monitor.state_for(route.route_id)
            if state == HealthState.UNAVAILABLE:
                return False

        if self.circuit_breaker and not self.circuit_breaker.is_route_active(route.route_id):
            return False

        return True

    def _effective_route(self, route: Route) -> Route:
        if not self.metrics_store:
            return route

        live_metrics = self.metrics_store.get(route.route_id)
        if live_metrics.total_requests == 0:
            return route

        observed_success = live_metrics.successful_requests / live_metrics.total_requests
        observed_failure = live_metrics.failed_requests / live_metrics.total_requests

        return replace(
            route,
            success_rate=observed_success,
            error_rate=observed_failure,
            latency_ms=live_metrics.average_latency,
        )
