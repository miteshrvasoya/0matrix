from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteMetrics:
    success_rate: float
    error_rate: float
    avg_latency: float
    sample_size: int
