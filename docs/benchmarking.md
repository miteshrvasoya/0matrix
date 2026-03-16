# Benchmarking

The benchmark framework lets you compare routing strategies offline before changing production traffic.

## What the Benchmark Framework Does

It simulates transaction traffic and route outcomes using the same strategy contract as production:

- generate payment contexts
- ask a strategy to choose a route
- simulate execution outcome for that route
- feed the result back through `record_outcome(...)`
- measure performance over many transactions

This is useful for:

- comparing strategies before rollout
- tuning weights and parameters
- validating new custom strategies
- regression-checking routing behavior after code changes

## Benchmark Components

### `TrafficSimulator`

Generates payment contexts and simulated execution outcomes.

It controls:

- payment methods
- regions
- amount range
- deterministic random seed
- route truth metrics used to simulate success and latency

### `StrategyBenchmarkRunner`

Runs repeated decisions over a batch of transactions.

For each strategy it:

1. builds an engine
2. generates contexts
3. chooses routes repeatedly
4. simulates route outcomes
5. updates strategy state with real outcomes
6. aggregates performance statistics

### `BenchmarkReport`

Formats benchmark output for:

- console display
- JSON export

## Metrics Reported

The current benchmark runner reports:

- `success_rate`
- `avg_latency_ms`
- `avg_cost`
- `cost_impact_vs_cheapest`
- `transactions`

Interpretation:

- higher `success_rate` is better
- lower `avg_latency_ms` is better
- lower `avg_cost` is better
- `cost_impact_vs_cheapest` shows how much more expensive the chosen routing mix was compared with always using the cheapest route

## Example Benchmark Run

```python
from benchmark.performance_report import build_report
from benchmark.strategy_benchmark import StrategyBenchmarkRunner
from benchmark.traffic_simulator import TrafficSimulator
from models.route_definition import RouteDefinition
from models.route_metrics import RouteMetrics
from strategies.contextual_bandit_router import ContextualBanditRouter
from strategies.epsilon_bandit_router import EpsilonBanditRouter
from strategies.predictive_failure_router import PredictiveFailureRouter
from strategies.thompson_sampling_router import ThompsonSamplingRouter
from strategies.weighted_router import WeightedRouter

routes = [
    RouteDefinition(name="route_a", cost=0.25, capacity=1000),
    RouteDefinition(name="route_b", cost=0.18, capacity=1000),
    RouteDefinition(name="route_c", cost=0.22, capacity=1000),
]

baseline_metrics = {
    "route_a": RouteMetrics(success_rate=0.96, error_rate=0.04, avg_latency=160, sample_size=2000),
    "route_b": RouteMetrics(success_rate=0.92, error_rate=0.08, avg_latency=90, sample_size=2000),
    "route_c": RouteMetrics(success_rate=0.94, error_rate=0.06, avg_latency=120, sample_size=2000),
}

simulator = TrafficSimulator(route_truth=baseline_metrics, seed=42)
runner = StrategyBenchmarkRunner(routes=routes, baseline_metrics=baseline_metrics, simulator=simulator)

results = runner.run(
    strategies={
        "weighted": WeightedRouter(),
        "epsilon_bandit": EpsilonBanditRouter(seed=42),
        "thompson": ThompsonSamplingRouter(seed=42),
        "contextual_bandit": ContextualBanditRouter(),
        "predictive_failure": PredictiveFailureRouter(),
    },
    transactions=5000,
)

report = build_report(results)
report.print_console()
report.write_json("benchmark_report.json")
```

## How to Read Results

### When Success Rate Wins

If one strategy has a meaningfully better success rate with acceptable latency and cost, that is usually a strong candidate for production testing.

### When Cost Wins But Success Drops

Be careful. A strategy that saves cost by selecting cheaper routes may still be a net loss if payment success falls materially.

### When Latency Improves But Success Is Flat

This is a good outcome for latency-sensitive experiences such as wallet or real-time card flows.

### When Adaptive Strategies Start Slowly

Adaptive strategies may perform worse in very short runs because they are still learning. Test both short and long horizons.

## Recommended Benchmark Scenarios

You usually want more than one benchmark scenario.

Suggested scenarios:

- stable environment with clear best route
- unstable environment where the best route changes over time
- high-cost vs high-success tradeoff environment
- issuer-sensitive or context-sensitive environment
- degradation scenario with rising latency and failures

## Benchmarking Best Practices

- use fixed seeds for reproducibility
- compare strategies on the same generated traffic
- keep route truth metrics realistic
- run enough transactions for adaptive strategies to learn
- benchmark with the same input scale and metric freshness you expect in production

## Adding a New Strategy to Benchmarking

A custom strategy automatically fits into the benchmark runner if it implements `BaseRoutingStrategy`.

```python
results = runner.run(
    strategies={
        "my_strategy": MyStrategy(),
    },
    transactions=5000,
)
```

## Relationship to Production

The benchmark framework is not a replacement for production validation.

Use it for:

- narrowing down candidate strategies
- tuning weights before rollout
- catching regressions in a controlled environment

Then validate the winner in:

- shadow mode
- canary rollout
- limited traffic experiments

## Related Files

- `benchmark/traffic_simulator.py`
- `benchmark/strategy_benchmark.py`
- `benchmark/performance_report.py`
- `tests/test_benchmark.py`
