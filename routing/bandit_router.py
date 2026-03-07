from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class BanditRouteState:
    route_id: str
    attempts: int = 0
    estimated_reward: float = 0.0


class EpsilonGreedyBanditRouter:
    """Adaptive router that balances exploration and exploitation."""

    def __init__(
        self,
        route_ids: list[str],
        epsilon: float = 0.1,
        success_weight: float = 0.8,
        latency_weight: float = 0.2,
        max_latency_ms: float = 2000.0,
        seed: int | None = None,
    ) -> None:
        if not route_ids:
            raise ValueError("route_ids must not be empty")
        if not 0.0 <= epsilon <= 1.0:
            raise ValueError("epsilon must be in [0.0, 1.0]")
        if success_weight < 0.0 or latency_weight < 0.0:
            raise ValueError("weights must be non-negative")
        if success_weight + latency_weight == 0.0:
            raise ValueError("at least one weight must be > 0")
        if max_latency_ms <= 0.0:
            raise ValueError("max_latency_ms must be > 0")

        total_weight = success_weight + latency_weight
        self.epsilon = epsilon
        self.success_weight = success_weight / total_weight
        self.latency_weight = latency_weight / total_weight
        self.max_latency_ms = max_latency_ms
        self.random = random.Random(seed)
        self._states: dict[str, BanditRouteState] = {
            route_id: BanditRouteState(route_id=route_id) for route_id in route_ids
        }

    def choose_route(self, route_ids: list[str]) -> str:
        self._validate_known_routes(route_ids)
        if self.random.random() < self.epsilon:
            return self.random.choice(route_ids)

        best_reward = max(self._states[route_id].estimated_reward for route_id in route_ids)
        best_route_ids = [
            route_id
            for route_id in route_ids
            if self._states[route_id].estimated_reward == best_reward
        ]
        return self.random.choice(best_route_ids)

    def update(self, route_id: str, success: bool, latency_ms: float) -> BanditRouteState:
        if route_id not in self._states:
            raise ValueError(f"unknown route_id={route_id}")

        reward = self.reward_for_attempt(success=success, latency_ms=latency_ms)
        state = self._states[route_id]
        state.attempts += 1
        state.estimated_reward += (reward - state.estimated_reward) / state.attempts
        return state

    def estimated_reward(self, route_id: str) -> float:
        if route_id not in self._states:
            raise ValueError(f"unknown route_id={route_id}")
        return self._states[route_id].estimated_reward

    def reward_for_attempt(self, success: bool, latency_ms: float) -> float:
        success_score = 1.0 if success else 0.0
        normalized_latency = min(max(latency_ms, 0.0), self.max_latency_ms) / self.max_latency_ms
        latency_score = 1.0 - normalized_latency
        return (self.success_weight * success_score) + (self.latency_weight * latency_score)

    def snapshot(self) -> dict[str, BanditRouteState]:
        return {route_id: state for route_id, state in self._states.items()}

    def _validate_known_routes(self, route_ids: list[str]) -> None:
        if not route_ids:
            raise ValueError("route_ids must not be empty")
        unknown_routes = [route_id for route_id in route_ids if route_id not in self._states]
        if unknown_routes:
            raise ValueError(f"unknown route_ids={unknown_routes}")
