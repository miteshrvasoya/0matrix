from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Mapping

from benchmark.traffic_simulator import TrafficSimulator
from core.base_strategy import BaseRoutingStrategy
from core.router_engine import RouterEngine
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics


@dataclass(frozen=True)
class StrategyBenchmarkResult:
    strategy_name: str
    transactions: int
    success_rate: float
    avg_latency_ms: float
    avg_cost: float
    cost_impact_vs_cheapest: float


class StrategyBenchmarkRunner:
    """Runs deterministic comparative benchmarks for routing strategies."""

    def __init__(
        self,
        routes: list[RouteDefinition],
        baseline_metrics: Mapping[str, RouteMetrics],
        simulator: TrafficSimulator,
    ) -> None:
        if not routes:
            raise ValueError("routes must not be empty")
        self.routes = routes
        self.baseline_metrics = dict(baseline_metrics)
        self.simulator = simulator

    def run(
        self, strategies: Mapping[str, BaseRoutingStrategy], transactions: int = 5000
    ) -> list[StrategyBenchmarkResult]:
        if transactions <= 0:
            raise ValueError("transactions must be > 0")

        contexts = self.simulator.generate_batch(transactions)
        cheapest_cost = min(route.cost for route in self.routes)
        results: list[StrategyBenchmarkResult] = []

        for strategy_name, strategy in strategies.items():
            engine = RouterEngine(strategy=strategy)
            dynamic_metrics = _clone_metrics(self.baseline_metrics)
            route_by_name = {route.name: route for route in self.routes}

            successes = 0
            latencies: list[float] = []
            costs: list[float] = []
            selections: defaultdict[str, int] = defaultdict(int)

            for context in contexts:
                decision = engine.route(context=context, routes=self.routes, metrics=dynamic_metrics)
                selected_route = route_by_name[decision.selected_route]
                outcome = self.simulator.simulate_outcome(selected_route)
                selections[selected_route.name] += 1
                if outcome.success:
                    successes += 1
                latencies.append(outcome.latency_ms)
                costs.append(outcome.cost)
                engine.record_outcome(
                    route_name=selected_route.name,
                    success=outcome.success,
                    latency_ms=outcome.latency_ms,
                    cost=outcome.cost,
                )
                dynamic_metrics[selected_route.name] = _update_metrics(
                    dynamic_metrics.get(selected_route.name), outcome.success, outcome.latency_ms
                )

            avg_cost = mean(costs) if costs else 0.0
            results.append(
                StrategyBenchmarkResult(
                    strategy_name=strategy_name,
                    transactions=transactions,
                    success_rate=successes / transactions,
                    avg_latency_ms=mean(latencies) if latencies else 0.0,
                    avg_cost=avg_cost,
                    cost_impact_vs_cheapest=(avg_cost / cheapest_cost) if cheapest_cost > 0 else 0.0,
                )
            )

        return sorted(results, key=lambda row: row.success_rate, reverse=True)


def _clone_metrics(metrics: Mapping[str, RouteMetrics]) -> dict[str, RouteMetrics]:
    return {
        name: RouteMetrics(
            success_rate=value.success_rate,
            error_rate=value.error_rate,
            avg_latency=value.avg_latency,
            sample_size=value.sample_size,
        )
        for name, value in metrics.items()
    }


def _update_metrics(current: RouteMetrics | None, success: bool, latency_ms: float) -> RouteMetrics:
    if current is None:
        current = RouteMetrics(success_rate=0.5, error_rate=0.5, avg_latency=1000.0, sample_size=0)

    next_sample = current.sample_size + 1
    prior_successes = current.success_rate * current.sample_size
    successes = prior_successes + (1.0 if success else 0.0)
    next_success_rate = successes / next_sample
    next_error_rate = 1.0 - next_success_rate
    next_latency = current.avg_latency + ((latency_ms - current.avg_latency) / next_sample)
    return RouteMetrics(
        success_rate=next_success_rate,
        error_rate=next_error_rate,
        avg_latency=next_latency,
        sample_size=next_sample,
    )
