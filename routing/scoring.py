from __future__ import annotations

from dataclasses import dataclass

from models import PaymentContext, Route


@dataclass(frozen=True)
class ScoreWeights:
    success_rate: float = 0.30
    latency: float = 0.20
    error_rate: float = 0.20
    cost: float = 0.15
    bank_affinity: float = 0.15


class ScoringAlgorithm:
    """Weighted scoring for route selection."""

    def __init__(self, weights: ScoreWeights | None = None) -> None:
        self.weights = weights or ScoreWeights()

    def score(self, route: Route, ctx: PaymentContext) -> float:
        success_component = route.success_rate
        latency_component = self._normalize_inverse(route.latency_ms, max_value=2000.0)
        error_component = 1.0 - route.error_rate
        cost_component = self._normalize_inverse(route.cost_per_txn, max_value=5.0)
        affinity_component = 1.0 if ctx.preferred_bank and route.bank_name == ctx.preferred_bank else 0.0

        w = self.weights
        return (
            w.success_rate * success_component
            + w.latency * latency_component
            + w.error_rate * error_component
            + w.cost * cost_component
            + w.bank_affinity * affinity_component
        )

    @staticmethod
    def _normalize_inverse(value: float, max_value: float) -> float:
        clamped = max(0.0, min(value, max_value))
        return 1.0 - (clamped / max_value)
