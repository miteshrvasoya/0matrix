from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from models.payment_context import PaymentContext
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics


@dataclass(frozen=True)
class SimulatedOutcome:
    success: bool
    latency_ms: float
    cost: float


class TrafficSimulator:
    """Generates payment traffic and route execution outcomes."""

    def __init__(
        self,
        route_truth: Mapping[str, RouteMetrics],
        *,
        payment_methods: tuple[str, ...] = ("card", "bank_transfer", "wallet"),
        regions: tuple[str, ...] = ("US", "EU", "APAC"),
        amount_range: tuple[float, float] = (5.0, 500.0),
        seed: int = 42,
    ) -> None:
        if amount_range[0] <= 0 or amount_range[1] <= amount_range[0]:
            raise ValueError("amount_range must be (min>0, max>min)")
        self.route_truth = dict(route_truth)
        self.payment_methods = payment_methods
        self.regions = regions
        self.amount_min, self.amount_max = amount_range
        self._rng = random.Random(seed)

    def generate_batch(self, count: int) -> list[PaymentContext]:
        if count <= 0:
            raise ValueError("count must be > 0")
        return [self.generate_context() for _ in range(count)]

    def generate_context(self) -> PaymentContext:
        return PaymentContext(
            amount=round(self._rng.uniform(self.amount_min, self.amount_max), 2),
            payment_method=self._rng.choice(self.payment_methods),
            payer_bank=None,
            region=self._rng.choice(self.regions),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def simulate_outcome(self, route: RouteDefinition) -> SimulatedOutcome:
        truth = self.route_truth.get(
            route.name,
            RouteMetrics(success_rate=0.5, error_rate=0.5, avg_latency=900.0, sample_size=0),
        )
        success = self._rng.random() <= max(0.0, min(1.0, truth.success_rate))
        latency = max(5.0, self._rng.gauss(truth.avg_latency, max(5.0, truth.avg_latency * 0.15)))
        return SimulatedOutcome(success=success, latency_ms=latency, cost=route.cost)
