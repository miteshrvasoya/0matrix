from __future__ import annotations

import random
from dataclasses import replace
from typing import Callable

from models import PaymentContext, Route, RoutingResult
from routing import (
    CircuitBreaker,
    HealthState,
    MetricsStore,
    RetryFailoverEngine,
    RouteHealthMonitor,
    RoutingEngine,
)


class BankRouteSimulator:
    """Simulates processing through selected bank routes with retry failover."""

    def __init__(
        self,
        engine: RoutingEngine,
        metrics_store: MetricsStore,
        health_monitor: RouteHealthMonitor,
        circuit_breaker: CircuitBreaker,
        failover_engine: RetryFailoverEngine,
        seed: int | None = 42,
        logger: Callable[[str], None] | None = print,
    ) -> None:
        self.engine = engine
        self.metrics_store = metrics_store
        self.health_monitor = health_monitor
        self.circuit_breaker = circuit_breaker
        self.failover_engine = failover_engine
        self.random = random.Random(seed)
        self.logger = logger

    def process_payment(self, ctx: PaymentContext) -> RoutingResult:
        ranked_decisions = self.engine.rank_routes(ctx)
        score_by_route_id = {item.route.route_id: item.score for item in ranked_decisions}
        ranked_routes = [item.route for item in ranked_decisions]

        def run_attempt(route: Route) -> RoutingResult:
            success = self.random.random() <= route.success_rate
            latency_ms = max(5.0, self.random.gauss(route.latency_ms, route.latency_ms * 0.15))

            error_code = None
            if not success:
                error_code = self._choose_error(route)

            self.metrics_store.record(route.route_id, success=success, latency_ms=latency_ms)
            self.engine.record_attempt(route.route_id, success=success, latency_ms=latency_ms)
            self._recalculate_route_health()

            return RoutingResult(
                payment_id=ctx.payment_id,
                chosen_route_id=route.route_id,
                chosen_bank=route.bank_name,
                score=round(score_by_route_id[route.route_id], 4),
                success=success,
                latency_ms=round(latency_ms, 2),
                error_code=error_code,
            )

        final_result, attempted_route_ids = self.failover_engine.execute(
            ctx=ctx,
            ranked_routes=ranked_routes,
            attempt_fn=run_attempt,
        )

        final_result = replace(
            final_result,
            retry_attempts=max(0, len(attempted_route_ids) - 1),
            attempted_route_ids=tuple(attempted_route_ids),
        )

        if self.logger:
            self.logger(
                f"PaymentID={ctx.payment_id} "
                f"ChosenRoute={final_result.chosen_route_id} "
                f"RetryAttempts={final_result.retry_attempts} "
                f"FinalResult={'SUCCESS' if final_result.success else 'FAILED'} "
                f"Latency={final_result.latency_ms}ms"
            )

        return final_result

    def _recalculate_route_health(self) -> None:
        for route_id in self.metrics_store.route_ids():
            failure_rate = self.metrics_store.recent_failure_rate(route_id)
            state = self.health_monitor.update_route(route_id, failure_rate)
            if state == HealthState.UNAVAILABLE:
                self.circuit_breaker.disable_route(route_id)

    def _choose_error(self, route: Route) -> str:
        # Weight timeout likelihood higher on high latency routes.
        timeout_bias = min(0.7, route.latency_ms / 3000.0)
        roll = self.random.random()
        if roll < timeout_bias:
            return "TIMEOUT"
        if roll < timeout_bias + 0.2:
            return "BANK_DECLINED"
        return "NETWORK_ERROR"
