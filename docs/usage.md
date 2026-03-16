# Usage Guide

This guide focuses on the day-to-day use of `smart-routing-algorithms`: creating engines, preparing inputs, selecting routes, feeding back outcomes, persisting strategy state, and extending the framework.

## 1. Basic Usage Pattern

Every decision uses the same pattern:

1. create or load a strategy
2. build `PaymentContext`
3. build `RouteDefinition` candidates
4. provide `RouteMetrics`
5. call `engine.route(...)`
6. execute the payment in the host system
7. call `engine.record_outcome(...)`

## 2. Create an Engine

### Load by Strategy Name

```python
from core.router_engine import RouterEngine

engine = RouterEngine(strategy="weighted")
```

This is usually the best option when the active strategy comes from configuration.

### Load by Strategy Instance

```python
from core.router_engine import RouterEngine
from strategies.contextual_bandit_router import ContextualBanditRouter

engine = RouterEngine(
    strategy=ContextualBanditRouter(
        route_preferences={
            "route_a": ["BankA"],
            "route_b": ["BankB"],
        },
        bank_affinity_bonus=0.10,
    )
)
```

This is useful when you want direct constructor control in code.

## 3. Build the Inputs

### Payment Context

```python
from models.payment_context import PaymentContext

context = PaymentContext(
    amount=249.99,
    payment_method="card",
    payer_bank="BankA",
    region="US",
    timestamp="2026-03-16T09:30:00Z",
)
```

Guidance:

- `amount`: numeric transaction amount used by context-sensitive strategies
- `payment_method`: such as `card`, `wallet`, `bank_transfer`
- `payer_bank`: optional issuer/bank hint used by contextual strategies
- `region`: host-defined routing region or geography label
- `timestamp`: used by time-aware strategies such as `ContextualBanditRouter`

### Route Definitions

```python
from models.route_definition import RouteDefinition

routes = [
    RouteDefinition(name="route_a", cost=0.32, capacity=1000),
    RouteDefinition(name="route_b", cost=0.18, capacity=1000),
]
```

Guidance:

- `name` must match the keys used in the metrics dictionary
- `cost` should be expressed in the same units across all routes
- `capacity <= 0` means the route will be ignored by built-in strategies

### Route Metrics

```python
from models.route_metrics import RouteMetrics

metrics = {
    "route_a": RouteMetrics(success_rate=0.97, error_rate=0.03, avg_latency=180, sample_size=2400),
    "route_b": RouteMetrics(success_rate=0.93, error_rate=0.07, avg_latency=95, sample_size=2500),
}
```

Guidance:

- `success_rate` and `error_rate` should be normalized values in `[0, 1]`
- `avg_latency` should be a consistent time unit, typically milliseconds
- `sample_size` represents how much evidence the metrics are based on

## 4. Make a Routing Decision

```python
decision = engine.route(context=context, routes=routes, metrics=metrics)

print(decision.selected_route)
print(decision.score)
print(decision.confidence)
```

Interpretation:

- `selected_route`: route name to execute
- `score`: strategy-specific ranking value, only directly comparable within the same strategy
- `confidence`: normalized confidence estimate, not a guaranteed probability of success

## 5. Feed Back Real Outcomes

After the host executes the payment, feed the real outcome back into the engine.

```python
engine.record_outcome(
    route_name=decision.selected_route,
    success=True,
    latency_ms=112.0,
    cost=0.18,
)
```

Why this matters:

- adaptive strategies learn from actual outcomes
- predictive strategies use recent latency and failure behavior
- snapshots become more useful over time

If you skip `record_outcome(...)`, deterministic strategies still work, but adaptive strategies will not improve.

## 6. Persist and Restore State

The framework never decides where state lives. Persist it in your own storage layer.

```python
snapshot = engine.snapshot_state()

# host persists snapshot
# db.save(strategy_name="thompson", state=snapshot)

engine.restore_state(snapshot)
```

Recommended persistence events:

- on graceful shutdown
- periodically on a timer
- after every N outcomes
- before strategy migrations or deploys

## 7. Switch Strategies Without Changing the Host Contract

This is one of the main benefits of the framework.

```python
engine = RouterEngine(strategy="weighted")
# later
engine = RouterEngine(strategy="thompson")
# later
engine = RouterEngine(strategy="predictive_failure")
```

The host still provides the same inputs and consumes the same `RoutingDecision` output.

## 8. Common Usage Patterns

### Pattern A: Configuration-Driven Strategy Selection

Store the active strategy and config in your control plane.

```python
strategy_name = "contextual_bandit"
strategy_config = {
    "bank_affinity_bonus": 0.12,
    "route_preferences": {
        "route_a": ["BankA"],
        "route_b": ["BankB"],
    },
}

engine = RouterEngine(strategy=strategy_name, config=strategy_config)
```

### Pattern B: Per-Merchant or Per-Region Engines

You can keep separate engines if merchants or regions should not share learning state.

Examples:

- one engine per merchant
- one engine per country
- one engine per payment method

### Pattern C: Warm Start After Restart

If you persist strategy state, you can avoid cold starts after deployment or process restart.

```python
engine = RouterEngine(strategy="thompson")
engine.restore_state(saved_snapshot)
```

## 9. Register a Custom Strategy

```python
from core.base_strategy import BaseRoutingStrategy
from core.strategy_registry import StrategyRegistry
from models.routing_decision import RoutingDecision

class LowestCostRouter(BaseRoutingStrategy):
    def choose_route(self, context, routes, metrics):
        route = min((r for r in routes if r.capacity > 0), key=lambda item: item.cost)
        return RoutingDecision(selected_route=route.name, score=-route.cost, confidence=1.0)

    def record_outcome(self, route_name, success, latency_ms, cost=None):
        pass

    def snapshot_state(self):
        return {}

    def restore_state(self, state):
        pass

StrategyRegistry.register("lowest_cost", LowestCostRouter, overwrite=True)
```

Then load it normally:

```python
engine = RouterEngine(strategy="lowest_cost")
```

## 10. Choose the Right Strategy

Start with these defaults:

- `WeightedRouter`: best baseline and easiest production rollout
- `EpsilonBanditRouter`: good first adaptive strategy
- `ThompsonSamplingRouter`: better when route evidence quality differs a lot
- `ContextualBanditRouter`: use when route performance changes by payment context
- `PredictiveFailureRouter`: use when route degradation happens before hard failure

For the detailed comparison, see [algorithms.md](algorithms.md).

## 11. Usage in Node.js and Go

The framework shape is the same:

- create engine
- provide context, routes, metrics
- call `route`
- feed `recordOutcome` / `RecordOutcome`

Node.js example:

```javascript
const { RouterEngine, WeightedRouter } = require("smart-router");
const engine = new RouterEngine(new WeightedRouter());
const decision = engine.route(context, routes, metrics);
engine.recordOutcome(decision.selected_route, true, 110.0, 0.18);
```

Go example:

```go
engine, _ := smartrouter.NewRouterEngine(smartrouter.NewWeightedRouter(nil))
decision, _ := engine.Route(ctx, routes, metrics)
engine.RecordOutcome(decision.SelectedRoute, true, 110.0, smartrouter.Float64Ptr(0.18))
```

## 12. Common Mistakes to Avoid

- Passing route names in `metrics` that do not exist in `routes`
- Mixing latency units across routes
- Forgetting to call `record_outcome(...)` for adaptive strategies
- Treating `confidence` as a guaranteed success probability
- Sharing the same strategy state across tenants that should be isolated

## 13. Next Reading

- [integration.md](integration.md) for production integration patterns
- [algorithms.md](algorithms.md) for strategy internals and tradeoffs
- [benchmarking.md](benchmarking.md) for offline evaluation
