from __future__ import annotations

from collections.abc import Callable

from models import PaymentContext, Route, RoutingResult
from routing.route_health import HealthState, RouteHealthMonitor


class RetryFailoverEngine:
    """Retries failed payments on next-best routes."""

    def __init__(self, max_retries: int = 3, health_monitor: RouteHealthMonitor | None = None) -> None:
        if max_retries <= 0:
            raise ValueError("max_retries must be > 0")
        self.max_retries = max_retries
        self.health_monitor = health_monitor

    def execute(
        self,
        ctx: PaymentContext,
        ranked_routes: list[Route],
        attempt_fn: Callable[[Route], RoutingResult],
    ) -> tuple[RoutingResult, list[str]]:
        attempted_route_ids: list[str] = []
        last_result: RoutingResult | None = None

        for route in ranked_routes:
            if len(attempted_route_ids) >= self.max_retries:
                break

            if self.health_monitor and self.health_monitor.state_for(route.route_id) == HealthState.UNAVAILABLE:
                continue

            attempted_route_ids.append(route.route_id)
            result = attempt_fn(route)
            last_result = result

            if result.success:
                return result, attempted_route_ids

        if last_result is None:
            raise ValueError(
                f"No available routes for payment={ctx.payment_id} under retry constraints"
            )

        return last_result, attempted_route_ids
