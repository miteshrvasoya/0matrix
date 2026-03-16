# Algorithms

This document explains all built-in routing strategies in the Python reference implementation: what data they use, how they score routes, what kind of state they maintain, and when each one is the right fit.

## Strategy Selection Summary

| Strategy | Type | Uses learning state | Best for |
| --- | --- | --- | --- |
| `WeightedRouter` | Deterministic scorer | Optional feedback fallback | Stable environments and transparent routing |
| `EpsilonBanditRouter` | Online bandit | Yes | Lightweight adaptive routing |
| `ThompsonSamplingRouter` | Bayesian bandit | Yes | Uncertainty-aware exploration |
| `ContextualBanditRouter` | Context-aware reward model | Yes | Route behavior that varies by payment context |
| `PredictiveFailureRouter` | Risk-aware scorer | Yes | Early degradation avoidance |

## Shared Concepts

Most strategies rely on some combination of these signals:

- success rate
- error rate
- latency
- cost
- sample size
- recent observed outcomes
- payment context features

Common normalization patterns in the framework:

- rates are treated as values in `[0, 1]`
- latency is normalized against a configurable `max_latency_ms`
- cost is normalized against a configurable `max_cost`
- confidence is normalized into `[0, 1]`

## Weighted Router

### Intuition

`WeightedRouter` is the baseline strategy. It does not try to explore or model uncertainty. It simply converts route quality into a deterministic weighted score.

### Inputs Used

- `success_rate`
- `error_rate`
- `avg_latency`
- `route.cost`

### Scoring Logic

At a high level:

```text
score =
  success_weight * success_rate
+ latency_weight * inverse_latency
+ cost_weight * inverse_cost
+ error_weight * inverse_error_rate
```

Where:

- `inverse_latency = 1 - normalized_latency`
- `inverse_cost = 1 - normalized_cost`
- `inverse_error_rate = 1 - error_rate`

### Decision Flow

1. Drop routes with `capacity <= 0`.
2. Resolve metrics for each route.
3. Normalize all inputs.
4. Compute a weighted score.
5. Select the highest score.
6. Use route name as deterministic tie-break.

### State Behavior

It can consume outcome feedback and use that as a fallback when host metrics are missing, but it remains fundamentally deterministic.

### Advantages

- simplest strategy to reason about
- easy to explain to operations and finance teams
- predictable output under stable metrics

### Tradeoffs

- does not explicitly explore alternatives
- may react slowly when route quality changes quickly
- treats current metrics as ground truth even when sample sizes differ

### Best Use Cases

- first production rollout
- baseline for benchmarking
- environments where transparency matters more than exploration

## Epsilon Bandit Router

### Intuition

`EpsilonBanditRouter` is a classic epsilon-greedy multi-armed bandit. Most of the time it chooses the route with the best learned reward, but sometimes it explores a different route intentionally.

### Inputs Used

- explicit feedback from `record_outcome(...)`
- normalized latency
- success outcome

### Reward Logic

```text
reward =
  success_weight * success_signal
+ latency_weight * inverse_latency
```

Where:

- `success_signal` is `1` for success and `0` for failure
- `inverse_latency = 1 - normalized_latency`

### Decision Flow

1. Drop routes with `capacity <= 0`.
2. Force cold-start exploration for routes with no observations.
3. With probability `epsilon`, explore a random route.
4. Otherwise select the route with the highest learned reward.
5. Update route reward after the actual outcome is known.

### State Behavior

Per route it keeps:

- number of attempts
- estimated reward

### Advantages

- simple adaptive routing
- fast to learn online
- very cheap computationally

### Tradeoffs

- exploration rate is manual
- uncertainty is not modeled explicitly
- bad `epsilon` tuning can over-explore or under-explore

### Best Use Cases

- you want a low-complexity adaptive strategy
- you have steady feedback volume
- you want direct control over exploration intensity

## Thompson Sampling Router

### Intuition

`ThompsonSamplingRouter` is also a bandit strategy, but instead of exploring with a fixed probability, it samples from a posterior distribution for each route. Routes with more uncertainty naturally get explored more often.

### Inputs Used

- host metrics: `success_rate`, `sample_size`, `avg_latency`
- explicit feedback from `record_outcome(...)`

### Bayesian Model

For each route:

```text
success_count = round(success_rate * sample_size)
failure_count = sample_size - success_count
sampled_success = Beta(success_count + learned_successes + 1,
                       failure_count + learned_failures + 1)
score = sampled_success - latency_penalty
```

Latency penalty:

```text
latency_penalty = latency_penalty_weight * normalized_latency
```

### Decision Flow

1. Drop routes with `capacity <= 0`.
2. Derive route success and failure counts from metrics.
3. Blend those counts with learned feedback state.
4. Sample a success probability from `random.betavariate(...)`.
5. Subtract a normalized latency penalty.
6. Select the highest sampled score.

### State Behavior

Per route it keeps:

- learned successes
- learned failures
- observation count
- average latency seen in feedback

### Advantages

- exploration is driven by uncertainty rather than a fixed random rate
- naturally favors routes with stronger evidence over weak evidence
- very strong default for adaptive routing

### Tradeoffs

- output is probabilistic, so route selection is less intuitive than fixed scoring
- good metrics quality still matters a lot

### Best Use Cases

- sample sizes differ significantly across routes
- you want adaptive routing without hand-tuning `epsilon`
- route quality is uncertain or changing frequently

## Contextual Bandit Router

### Intuition

`ContextualBanditRouter` chooses routes based not only on route metrics, but also on payment characteristics. The same route may be good for one issuer, amount segment, or time window and mediocre for another.

### Inputs Used

- `payer_bank`
- `payment_method`
- `amount`
- `timestamp` / time of day
- route metrics
- route cost
- optional route preference map
- prior observed contextual rewards

### Feature Extraction

The built-in implementation derives a compact context signature from:

- payer bank
- payment method
- amount band: `low`, `medium`, `high`
- time of day: `morning`, `afternoon`, `evening`, `night`

### Reward Logic

Base reward:

```text
reward =
  success_rate_weight * success_rate
- latency_weight * normalized_latency
- cost_weight * normalized_cost
+ bank_affinity_bonus
```

Then the strategy blends that base reward with previously observed contextual reward for the same route and similar context.

### Decision Flow

1. Drop routes with `capacity <= 0`.
2. Extract context features from the payment.
3. Adjust reward weights for amount band, payment method, and time of day.
4. Compute a predicted reward for each route.
5. Apply bank affinity bonus when configured or inferred.
6. Blend base reward with historical contextual reward.
7. Select the route with the highest reward.

### State Behavior

It keeps:

- average reward per route
- average reward per route and context signature
- pending context assignments so feedback can be matched to the route decision that produced it

### Advantages

- better than global scoring when performance depends on payment shape
- can learn different route preferences for different issuer or method populations
- supports operational bank affinity rules without changing core models

### Tradeoffs

- more stateful than simple bandits
- requires reasonably consistent payment context fields
- bad or sparse context data reduces its advantage

### Best Use Cases

- issuer-dependent card performance
- different route behavior by method or amount segment
- time-dependent route quality differences

## Predictive Failure Router

### Intuition

`PredictiveFailureRouter` tries to spot routes that are starting to degrade before aggregate metrics fully reflect the problem. It treats rising latency, error spikes, and instability as early warning signals.

### Inputs Used

- route metrics: `success_rate`, `error_rate`, `avg_latency`
- recent route outcomes recorded through `record_outcome(...)`

### Risk Logic

```text
risk_score =
  latency_trend_weight * latency_growth
+ error_trend_weight * error_rate_or_spike
+ instability_weight * latency_variance

score = success_rate - latency_penalty - risk_score
```

Where:

- `latency_growth` compares recent latency behavior against earlier observations
- `error_rate_or_spike` reflects both current error rate and recent spike behavior
- `latency_variance` captures instability

### Decision Flow

1. Drop routes with `capacity <= 0`.
2. Resolve route metrics from host metrics or local history fallback.
3. Calculate route risk using recent recorded outcomes.
4. Subtract latency penalty and risk from success rate.
5. Select the route with the best risk-adjusted score.

### State Behavior

Per route it keeps bounded recent history of:

- latencies
- error signals

### Advantages

- reacts to early route instability
- useful when route deterioration appears before outright failure
- can be safer than pure success-rate optimization under operational stress

### Tradeoffs

- requires reliable outcome feedback
- more sensitive to short-term noise if history windows are badly tuned
- should usually be paired with sensible host-side route eligibility checks

### Best Use Cases

- routes that degrade gradually before going hard-down
- high-SLA environments where avoiding instability matters as much as raw average performance

## Confidence Semantics

Confidence is strategy-specific and should be read as a ranking confidence indicator, not as an exact payment success probability.

Current meanings:

- `WeightedRouter`: margin between the top two route scores
- `EpsilonBanditRouter`: stability of repeated selections under the same learned state
- `ThompsonSamplingRouter`: stability of repeated posterior samples
- `ContextualBanditRouter`: margin between predicted route rewards
- `PredictiveFailureRouter`: combination of top-score margin and inverse route risk

## Which Strategy Should You Start With?

A practical sequence is:

1. `WeightedRouter` for baseline rollout and observability
2. `ThompsonSamplingRouter` if you want a strong default adaptive strategy
3. `ContextualBanditRouter` if route quality clearly varies by payment context
4. `PredictiveFailureRouter` if operations show early route degradation patterns
5. `EpsilonBanditRouter` if you specifically want simple manual control over exploration

## Benchmark Before Production Changes

Even if an algorithm looks theoretically better, benchmark it against your own route mix and traffic patterns before rollout. See [benchmarking.md](benchmarking.md).
