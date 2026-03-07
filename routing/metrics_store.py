from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class RouteMetrics:
    route_id: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_latency: float = 0.0
    failure_rate: float = 0.0


class MetricsStore:
    """Tracks route-level metrics with O(1) updates for high-volume simulation."""

    def __init__(self, route_ids: list[str], recent_window: int = 100) -> None:
        if recent_window <= 0:
            raise ValueError("recent_window must be > 0")

        self._metrics: dict[str, RouteMetrics] = {
            route_id: RouteMetrics(route_id=route_id) for route_id in route_ids
        }
        self._recent_outcomes: dict[str, deque[bool]] = {
            route_id: deque(maxlen=recent_window) for route_id in route_ids
        }

    def record(self, route_id: str, success: bool, latency_ms: float) -> RouteMetrics:
        metrics = self._metrics[route_id]
        metrics.total_requests += 1

        if success:
            metrics.successful_requests += 1
        else:
            metrics.failed_requests += 1

        # Incremental running average keeps updates constant-time.
        total = metrics.total_requests
        metrics.average_latency += (latency_ms - metrics.average_latency) / total
        metrics.failure_rate = metrics.failed_requests / total

        self._recent_outcomes[route_id].append(success)
        return metrics

    def get(self, route_id: str) -> RouteMetrics:
        return self._metrics[route_id]

    def recent_failure_rate(self, route_id: str) -> float:
        outcomes = self._recent_outcomes[route_id]
        if not outcomes:
            return 0.0
        failures = sum(1 for ok in outcomes if not ok)
        return failures / len(outcomes)

    def route_ids(self) -> list[str]:
        return list(self._metrics.keys())

    def snapshot(self) -> dict[str, RouteMetrics]:
        return {route_id: self.get(route_id) for route_id in self._metrics}
