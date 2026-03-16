from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping

from core.base_strategy import BaseRoutingStrategy
from models.payment_context import PaymentContext
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics
from models.routing_decision import RoutingDecision


@dataclass(frozen=True)
class _ContextFeatures:
    payer_bank: str
    payment_method: str
    amount_band: str
    time_of_day: str


@dataclass
class _RewardStats:
    observations: int = 0
    average_reward: float = 0.0


class ContextualBanditRouter(BaseRoutingStrategy):
    """Context-aware reward router using payment features and lightweight feedback."""

    def __init__(
        self,
        success_rate_weight: float = 0.55,
        latency_weight: float = 0.25,
        cost_weight: float = 0.20,
        bank_affinity_bonus: float = 0.08,
        learned_reward_weight: float = 0.35,
        max_latency_ms: float = 2000.0,
        max_cost: float = 5.0,
        route_preferences: Mapping[str, Iterable[str] | str] | None = None,
    ) -> None:
        if max_latency_ms <= 0.0:
            raise ValueError("max_latency_ms must be > 0")
        if max_cost <= 0.0:
            raise ValueError("max_cost must be > 0")
        if bank_affinity_bonus < 0.0:
            raise ValueError("bank_affinity_bonus must be >= 0")
        if not 0.0 <= learned_reward_weight <= 1.0:
            raise ValueError("learned_reward_weight must be in [0, 1]")

        total_weight = success_rate_weight + latency_weight + cost_weight
        if total_weight <= 0.0:
            raise ValueError("at least one weight must be > 0")

        self.success_rate_weight = success_rate_weight / total_weight
        self.latency_weight = latency_weight / total_weight
        self.cost_weight = cost_weight / total_weight
        self.bank_affinity_bonus = bank_affinity_bonus
        self.learned_reward_weight = learned_reward_weight
        self.max_latency_ms = max_latency_ms
        self.max_cost = max_cost
        self._route_preferences = _normalize_preferences(route_preferences or {})
        self._route_context_stats: dict[str, dict[str, _RewardStats]] = {}
        self._route_stats: dict[str, _RewardStats] = {}
        self._pending_contexts: dict[str, deque[str]] = {}

    def choose_route(
        self,
        context: PaymentContext,
        routes: list[RouteDefinition],
        metrics: Mapping[str, RouteMetrics] | None,
    ) -> RoutingDecision:
        available = sorted((route for route in routes if route.capacity > 0), key=lambda item: item.name)
        if not available:
            raise ValueError("no routes with positive capacity")

        metric_map = metrics or {}
        scored: list[tuple[str, float]] = []
        feature_key = self._feature_key(context)
        for route in available:
            score = self.predict_reward(context=context, route=route, metrics=metric_map)
            scored.append((route.name, score))

        scored.sort(key=lambda item: (-item[1], item[0]))
        selected_route, selected_score = scored[0]
        self._pending_contexts.setdefault(selected_route, deque()).append(feature_key)
        return RoutingDecision(
            selected_route=selected_route,
            score=round(selected_score, 6),
            confidence=round(_confidence_from_margin(scored), 6),
        )

    def predict_reward(
        self,
        context: PaymentContext,
        route: RouteDefinition,
        metrics: Mapping[str, RouteMetrics],
    ) -> float:
        features = self._extract_features(context)
        weights = self._resolve_context_weights(features)
        route_metrics = self._resolve_metrics(route.name, metrics)
        success_component = _clamp(route_metrics.success_rate)
        latency_penalty = _clamp(route_metrics.avg_latency / self.max_latency_ms)
        cost_penalty = _clamp(route.cost / self.max_cost)

        base_reward = (
            (weights["success"] * success_component)
            - (weights["latency"] * latency_penalty)
            - (weights["cost"] * cost_penalty)
        )
        learned_reward = self._learned_reward(route.name, self._feature_key(context), base_reward)
        affinity_bonus = self.bank_affinity_bonus if self._has_bank_affinity(route.name, features) else 0.0
        return ((1.0 - self.learned_reward_weight) * base_reward) + (
            self.learned_reward_weight * learned_reward
        ) + affinity_bonus

    def record_outcome(
        self,
        route_name: str,
        success: bool,
        latency_ms: float,
        cost: float | None = None,
    ) -> None:
        context_queue = self._pending_contexts.setdefault(route_name, deque())
        feature_key = context_queue.popleft() if context_queue else "__default__"
        observed_reward = self._observed_reward(success=success, latency_ms=latency_ms, cost=cost or 0.0)
        self._update_stats(self._route_stats.setdefault(route_name, _RewardStats()), observed_reward)
        route_contexts = self._route_context_stats.setdefault(route_name, {})
        self._update_stats(route_contexts.setdefault(feature_key, _RewardStats()), observed_reward)

    def snapshot_state(self) -> dict:
        return {
            "route_stats": {
                route_name: {
                    "observations": stats.observations,
                    "average_reward": stats.average_reward,
                }
                for route_name, stats in self._route_stats.items()
            },
            "route_context_stats": {
                route_name: {
                    feature_key: {
                        "observations": stats.observations,
                        "average_reward": stats.average_reward,
                    }
                    for feature_key, stats in context_stats.items()
                }
                for route_name, context_stats in self._route_context_stats.items()
            },
        }

    def restore_state(self, state: dict) -> None:
        self._route_stats = {}
        for route_name, raw in state.get("route_stats", {}).items():
            self._route_stats[route_name] = _RewardStats(
                observations=int(raw.get("observations", 0)),
                average_reward=float(raw.get("average_reward", 0.0)),
            )

        self._route_context_stats = {}
        for route_name, raw_contexts in state.get("route_context_stats", {}).items():
            contexts: dict[str, _RewardStats] = {}
            for feature_key, raw in raw_contexts.items():
                contexts[feature_key] = _RewardStats(
                    observations=int(raw.get("observations", 0)),
                    average_reward=float(raw.get("average_reward", 0.0)),
                )
            self._route_context_stats[route_name] = contexts
        self._pending_contexts = {}

    def _resolve_metrics(
        self,
        route_name: str,
        metrics: Mapping[str, RouteMetrics],
    ) -> RouteMetrics:
        if route_name in metrics:
            return metrics[route_name]

        route_stats = self._route_stats.get(route_name)
        if route_stats and route_stats.observations > 0:
            success_rate = _clamp(route_stats.average_reward + 0.5)
            return RouteMetrics(
                success_rate=success_rate,
                error_rate=1.0 - success_rate,
                avg_latency=1000.0,
                sample_size=route_stats.observations,
            )

        return RouteMetrics(success_rate=0.5, error_rate=0.5, avg_latency=1000.0, sample_size=0)

    def _learned_reward(self, route_name: str, feature_key: str, base_reward: float) -> float:
        route_contexts = self._route_context_stats.get(route_name, {})
        specific = route_contexts.get(feature_key)
        if specific and specific.observations > 0:
            return specific.average_reward

        overall = self._route_stats.get(route_name)
        if overall and overall.observations > 0:
            return overall.average_reward
        return base_reward

    def _has_bank_affinity(self, route_name: str, features: _ContextFeatures) -> bool:
        if not features.payer_bank:
            return False
        preferred_banks = self._route_preferences.get(route_name, set())
        if preferred_banks:
            return features.payer_bank in preferred_banks
        return features.payer_bank.replace(" ", "") in route_name.lower().replace("_", "")

    def _observed_reward(self, success: bool, latency_ms: float, cost: float) -> float:
        return (
            (self.success_rate_weight * (1.0 if success else 0.0))
            - (self.latency_weight * _clamp(latency_ms / self.max_latency_ms))
            - (self.cost_weight * _clamp(cost / self.max_cost))
        )

    def _resolve_context_weights(self, features: _ContextFeatures) -> dict[str, float]:
        success = self.success_rate_weight
        latency = self.latency_weight
        cost = self.cost_weight

        if features.amount_band == "high":
            success += 0.10
            cost = max(0.01, cost - 0.05)
        elif features.amount_band == "low":
            cost += 0.05

        if features.payment_method in {"wallet", "upi"}:
            latency += 0.08
        elif features.payment_method == "bank_transfer":
            success += 0.05

        if features.time_of_day in {"evening", "night"}:
            latency += 0.05

        total = success + latency + cost
        return {
            "success": success / total,
            "latency": latency / total,
            "cost": cost / total,
        }

    def _extract_features(self, context: PaymentContext) -> _ContextFeatures:
        payer_bank = (context.payer_bank or "").strip().lower()
        payment_method = context.payment_method.strip().lower()
        amount_band = _amount_band(context.amount)
        time_of_day = _time_of_day(context.timestamp)
        return _ContextFeatures(
            payer_bank=payer_bank,
            payment_method=payment_method,
            amount_band=amount_band,
            time_of_day=time_of_day,
        )

    def _feature_key(self, context: PaymentContext) -> str:
        features = self._extract_features(context)
        return "|".join(
            [
                features.payer_bank or "none",
                features.payment_method,
                features.amount_band,
                features.time_of_day,
            ]
        )

    @staticmethod
    def _update_stats(stats: _RewardStats, reward: float) -> None:
        stats.observations += 1
        stats.average_reward += (reward - stats.average_reward) / stats.observations


def _amount_band(amount: float) -> str:
    if amount < 100.0:
        return "low"
    if amount < 500.0:
        return "medium"
    return "high"


def _time_of_day(timestamp: datetime | str) -> str:
    if isinstance(timestamp, datetime):
        hour = timestamp.hour
    else:
        normalized = timestamp.replace("Z", "+00:00")
        hour = datetime.fromisoformat(normalized).hour
    if 6 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def _normalize_preferences(
    route_preferences: Mapping[str, Iterable[str] | str],
) -> dict[str, set[str]]:
    normalized: dict[str, set[str]] = {}
    for route_name, banks in route_preferences.items():
        if isinstance(banks, str):
            normalized[route_name] = {banks.strip().lower()}
        else:
            normalized[route_name] = {bank.strip().lower() for bank in banks}
    return normalized


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _confidence_from_margin(scored: list[tuple[str, float]]) -> float:
    if len(scored) == 1:
        return 1.0
    return _clamp(scored[0][1] - scored[1][1])
