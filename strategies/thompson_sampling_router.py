from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Mapping

from core.base_strategy import BaseRoutingStrategy
from models.payment_context import PaymentContext
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics
from models.routing_decision import RoutingDecision


@dataclass
class _RoutePosterior:
    successes: int = 0
    failures: int = 0
    observations: int = 0
    avg_latency: float = 1000.0


class ThompsonSamplingRouter(BaseRoutingStrategy):
    """Bayesian router using Beta posteriors and latency-adjusted route scores."""

    def __init__(
        self,
        latency_penalty_weight: float = 0.10,
        max_latency_ms: float = 2000.0,
        confidence_trials: int = 300,
        seed: int = 42,
    ) -> None:
        if latency_penalty_weight < 0.0:
            raise ValueError("latency_penalty_weight must be >= 0")
        if max_latency_ms <= 0.0:
            raise ValueError("max_latency_ms must be > 0")
        if confidence_trials <= 0:
            raise ValueError("confidence_trials must be > 0")

        self.latency_penalty_weight = latency_penalty_weight
        self.max_latency_ms = max_latency_ms
        self.confidence_trials = confidence_trials
        self.seed = seed
        self._rng = random.Random(seed)
        self._state: dict[str, _RoutePosterior] = {}

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
        for route in available:
            alpha, beta = self._posterior_parameters(route.name, metric_map)
            sampled_success = self._rng.betavariate(alpha, beta)
            latency_penalty = self.latency_penalty_weight * self._normalized_latency(
                route.name, metric_map
            )
            scored.append((route.name, sampled_success - latency_penalty))

        scored.sort(key=lambda item: (-item[1], item[0]))
        selected_route, selected_score = scored[0]
        confidence = self._estimate_confidence(selected_route, [route.name for route in available], metric_map)
        return RoutingDecision(
            selected_route=selected_route,
            score=round(selected_score, 6),
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
        state = self._state.setdefault(route_name, _RoutePosterior())
        state.observations += 1
        if success:
            state.successes += 1
        else:
            state.failures += 1
        state.avg_latency += (latency_ms - state.avg_latency) / state.observations

    def snapshot_state(self) -> dict:
        return {
            "latency_penalty_weight": self.latency_penalty_weight,
            "max_latency_ms": self.max_latency_ms,
            "seed": self.seed,
            "state": {
                route_name: {
                    "successes": state.successes,
                    "failures": state.failures,
                    "observations": state.observations,
                    "avg_latency": state.avg_latency,
                }
                for route_name, state in self._state.items()
            },
        }

    def restore_state(self, state: dict) -> None:
        restored: dict[str, _RoutePosterior] = {}
        for route_name, raw in state.get("state", {}).items():
            restored[route_name] = _RoutePosterior(
                successes=int(raw.get("successes", 0)),
                failures=int(raw.get("failures", 0)),
                observations=int(raw.get("observations", 0)),
                avg_latency=float(raw.get("avg_latency", 1000.0)),
            )
        self._state = restored

    def _posterior_parameters(
        self,
        route_name: str,
        metrics: Mapping[str, RouteMetrics],
    ) -> tuple[float, float]:
        metric_successes = 0
        metric_failures = 0
        metric = metrics.get(route_name)
        if metric is not None and metric.sample_size > 0:
            metric_successes = max(
                0,
                min(metric.sample_size, int(round(metric.success_rate * metric.sample_size))),
            )
            metric_failures = max(0, metric.sample_size - metric_successes)

        state = self._state.get(route_name, _RoutePosterior())
        alpha = metric_successes + state.successes + 1.0
        beta = metric_failures + state.failures + 1.0
        return alpha, beta

    def _normalized_latency(self, route_name: str, metrics: Mapping[str, RouteMetrics]) -> float:
        metric = metrics.get(route_name)
        if metric is not None:
            return _clamp(metric.avg_latency / self.max_latency_ms)
        state = self._state.get(route_name)
        if state is None:
            return 0.5
        return _clamp(state.avg_latency / self.max_latency_ms)

    def _estimate_confidence(
        self,
        selected_route: str,
        route_names: list[str],
        metrics: Mapping[str, RouteMetrics],
    ) -> float:
        wins = 0
        simulated_rng = random.Random(_stable_seed(self.seed, route_names, self._state, metrics))
        for _ in range(self.confidence_trials):
            winner = self._sample_once(route_names, metrics, simulated_rng)
            if winner == selected_route:
                wins += 1
        return wins / self.confidence_trials

    def _sample_once(
        self,
        route_names: list[str],
        metrics: Mapping[str, RouteMetrics],
        rng: random.Random,
    ) -> str:
        best_route = route_names[0]
        best_score = float("-inf")
        for route_name in route_names:
            alpha, beta = self._posterior_parameters(route_name, metrics)
            sampled_success = rng.betavariate(alpha, beta)
            latency_penalty = self.latency_penalty_weight * self._normalized_latency(
                route_name,
                metrics,
            )
            score = sampled_success - latency_penalty
            if score > best_score or (score == best_score and route_name < best_route):
                best_score = score
                best_route = route_name
        return best_route


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _stable_seed(
    seed: int,
    route_names: list[str],
    state: Mapping[str, _RoutePosterior],
    metrics: Mapping[str, RouteMetrics],
) -> int:
    payload = "|".join(
        [
            str(seed),
            ",".join(route_names),
            ",".join(
                f"{name}:{state[name].successes}:{state[name].failures}:{state[name].observations}:{state[name].avg_latency:.6f}"
                for name in sorted(state.keys())
            ),
            ",".join(
                f"{name}:{metrics[name].success_rate:.6f}:{metrics[name].error_rate:.6f}:{metrics[name].avg_latency:.6f}:{metrics[name].sample_size}"
                for name in sorted(metrics.keys())
            ),
        ]
    )
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16], 16)
