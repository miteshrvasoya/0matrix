from __future__ import annotations

from enum import Enum


class HealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class RouteHealthMonitor:
    """Evaluates and stores health state for each route."""

    def __init__(self) -> None:
        self._state_by_route: dict[str, HealthState] = {}

    def evaluate(self, failure_rate: float) -> HealthState:
        if failure_rate > 0.30:
            return HealthState.UNAVAILABLE
        if 0.10 <= failure_rate <= 0.30:
            return HealthState.DEGRADED
        return HealthState.HEALTHY

    def update_route(self, route_id: str, failure_rate: float) -> HealthState:
        state = self.evaluate(failure_rate)
        self._state_by_route[route_id] = state
        return state

    def state_for(self, route_id: str) -> HealthState:
        return self._state_by_route.get(route_id, HealthState.HEALTHY)

    def snapshot(self) -> dict[str, HealthState]:
        return dict(self._state_by_route)
