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
class _BanditState:
    attempts: int = 0
    estimated_reward: float = 0.0


class EpsilonBanditRouter(BaseRoutingStrategy):
    """Epsilon-greedy multi-armed bandit router."""

    def __init__(
        self,
        epsilon: float = 0.10,
        success_weight: float = 0.70,
        latency_weight: float = 0.30,
        max_latency_ms: float = 2000.0,
        confidence_trials: int = 300,
        seed: int = 42,
    ) -> None:
        if not 0.0 <= epsilon <= 1.0:
            raise ValueError("epsilon must be in [0, 1]")
        if max_latency_ms <= 0:
            raise ValueError("max_latency_ms must be > 0")
        if confidence_trials <= 0:
            raise ValueError("confidence_trials must be > 0")
        total = success_weight + latency_weight
        if total <= 0:
            raise ValueError("success_weight + latency_weight must be > 0")

        self.epsilon = epsilon
        self.success_weight = success_weight / total
        self.latency_weight = latency_weight / total
        self.max_latency_ms = max_latency_ms
        self.confidence_trials = confidence_trials
        self.seed = seed
        self._rng = random.Random(seed)
        self._state: dict[str, _BanditState] = {}

    def choose_route(
        self,
        context: PaymentContext,
        routes: list[RouteDefinition],
        metrics: Mapping[str, RouteMetrics] | None,
    ) -> RoutingDecision:
        del context
        del metrics

        eligible = sorted((route for route in routes if route.capacity > 0), key=lambda route: route.name)
        if not eligible:
            raise ValueError("no routes with positive capacity")

        eligible_names = [route.name for route in eligible]
        self._ensure_routes(eligible_names)
        selected = self._select_route(eligible_names, self._rng)
        score = self._state[selected].estimated_reward
        confidence = self._estimate_confidence(selected, eligible_names)
        return RoutingDecision(
            selected_route=selected,
            score=round(score, 6),
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
        self._ensure_routes([route_name])
        reward = self._reward(success, latency_ms)
        state = self._state[route_name]
        state.attempts += 1
        state.estimated_reward += (reward - state.estimated_reward) / state.attempts

    def snapshot_state(self) -> dict:
        return {
            "epsilon": self.epsilon,
            "success_weight": self.success_weight,
            "latency_weight": self.latency_weight,
            "max_latency_ms": self.max_latency_ms,
            "seed": self.seed,
            "state": {
                route: {
                    "attempts": data.attempts,
                    "estimated_reward": data.estimated_reward,
                }
                for route, data in self._state.items()
            },
        }

    def restore_state(self, state: dict) -> None:
        self._state = {}
        for route_name, raw in state.get("state", {}).items():
            self._state[route_name] = _BanditState(
                attempts=int(raw.get("attempts", 0)),
                estimated_reward=float(raw.get("estimated_reward", 0.0)),
            )

    def _reward(self, success: bool, latency_ms: float) -> float:
        success_component = 1.0 if success else 0.0
        latency_score = 1.0 - _clamp(latency_ms / self.max_latency_ms)
        return (self.success_weight * success_component) + (self.latency_weight * latency_score)

    def _select_route(self, route_names: list[str], rng: random.Random) -> str:
        unseen = [name for name in route_names if self._state[name].attempts == 0]
        if unseen:
            return unseen[0]
        if rng.random() < self.epsilon:
            return rng.choice(route_names)

        best_score = max(self._state[name].estimated_reward for name in route_names)
        best_routes = [
            name for name in route_names if self._state[name].estimated_reward == best_score
        ]
        return min(best_routes)

    def _estimate_confidence(self, selected_route: str, route_names: list[str]) -> float:
        wins = 0
        simulated_rng = random.Random(_stable_seed(self.seed, self._state, route_names))
        for _ in range(self.confidence_trials):
            if self._select_route(route_names, simulated_rng) == selected_route:
                wins += 1
        return wins / self.confidence_trials

    def _ensure_routes(self, route_names: list[str]) -> None:
        for route_name in route_names:
            self._state.setdefault(route_name, _BanditState())


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _stable_seed(seed: int, state: Mapping[str, _BanditState], route_names: list[str]) -> int:
    payload = "|".join(
        [
            str(seed),
            ",".join(route_names),
            ",".join(
                f"{name}:{state[name].attempts}:{state[name].estimated_reward:.8f}"
                for name in sorted(state.keys())
            ),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)
