"use strict";

const REGISTRY = new Map();

function clamp(value, min = 0, max = 1) {
  return Math.max(min, Math.min(max, value));
}

function hashString(input) {
  let hash = 2166136261;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

class RNG {
  constructor(seed = 42) {
    this.state = seed >>> 0;
  }

  next() {
    let t = (this.state += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  choice(values) {
    return values[Math.floor(this.next() * values.length)];
  }

  fork(salt) {
    return new RNG(hashString(`${this.state}:${salt}`));
  }
}

function gaussian(rng) {
  const u1 = Math.max(rng.next(), 1e-12);
  const u2 = rng.next();
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

function gammaSample(shape, rng) {
  if (shape <= 0) {
    throw new Error("shape must be > 0");
  }
  if (shape < 1) {
    return gammaSample(shape + 1, rng) * Math.pow(rng.next(), 1 / shape);
  }

  const d = shape - 1 / 3;
  const c = 1 / Math.sqrt(9 * d);
  while (true) {
    const x = gaussian(rng);
    const v = Math.pow(1 + c * x, 3);
    if (v <= 0) {
      continue;
    }
    const u = rng.next();
    if (u < 1 - 0.0331 * Math.pow(x, 4)) {
      return d * v;
    }
    if (Math.log(u) < 0.5 * x * x + d * (1 - v + Math.log(v))) {
      return d * v;
    }
  }
}

function betaSample(alpha, beta, rng) {
  const x = gammaSample(alpha, rng);
  const y = gammaSample(beta, rng);
  return x / (x + y);
}

class BaseRoutingStrategy {
  chooseRoute(_context, _routes, _metrics) {
    throw new Error("chooseRoute must be implemented by subclasses");
  }

  recordOutcome(_routeName, _success, _latencyMs, _cost = null) {}

  snapshotState() {
    return {};
  }

  restoreState(_state) {}
}

class StrategyRegistry {
  static register(name, factory, { overwrite = false } = {}) {
    const key = String(name || "").trim().toLowerCase();
    if (!key) {
      throw new Error("strategy name must not be empty");
    }
    if (!overwrite && REGISTRY.has(key)) {
      throw new Error(`strategy '${key}' is already registered`);
    }
    REGISTRY.set(key, factory);
  }

  static create(name, config = {}) {
    const key = String(name || "").trim().toLowerCase();
    if (!REGISTRY.has(key)) {
      throw new Error(`strategy '${key}' is not registered`);
    }
    const factory = REGISTRY.get(key);
    let instance;
    if (factory.prototype && typeof factory.prototype.chooseRoute === "function") {
      instance = new factory(config);
    } else {
      instance = factory(config);
    }
    if (!instance || typeof instance.chooseRoute !== "function") {
      throw new Error(`factory '${key}' did not return a routing strategy`);
    }
    return instance;
  }

  static list() {
    return Array.from(REGISTRY.keys()).sort();
  }

  static autodiscover(modules = []) {
    for (const modulePath of modules) {
      const loaded = require(modulePath); // eslint-disable-line global-require, import/no-dynamic-require
      if (loaded && typeof loaded.registerStrategies === "function") {
        loaded.registerStrategies(this);
      } else if (loaded && typeof loaded.default === "function") {
        loaded.default(this);
      }
    }
  }
}

class RouterEngine {
  constructor(strategy) {
    if (!strategy || typeof strategy.chooseRoute !== "function") {
      throw new Error("strategy must implement chooseRoute(context, routes, metrics)");
    }
    this.strategy = strategy;
  }

  static fromRegistry(name, config = {}) {
    return new RouterEngine(StrategyRegistry.create(name, config));
  }

  route(context, routes, metrics = {}) {
    if (!Array.isArray(routes) || routes.length === 0) {
      throw new Error("routes must not be empty");
    }
    const decision = this.strategy.chooseRoute(context, routes, metrics || {});
    if (!decision || typeof decision.selected_route !== "string") {
      throw new Error("strategy returned invalid decision");
    }
    if (decision.confidence < 0 || decision.confidence > 1) {
      throw new Error("strategy confidence must be in [0, 1]");
    }
    return decision;
  }

  recordOutcome(routeName, success, latencyMs, cost = null) {
    if (typeof this.strategy.recordOutcome === "function") {
      this.strategy.recordOutcome(routeName, success, latencyMs, cost);
    }
  }

  snapshotState() {
    return typeof this.strategy.snapshotState === "function" ? this.strategy.snapshotState() : {};
  }

  restoreState(state) {
    if (typeof this.strategy.restoreState === "function") {
      this.strategy.restoreState(state);
    }
  }
}

class WeightedRouter extends BaseRoutingStrategy {
  constructor(config = {}) {
    super();
    const successWeight = config.successWeight ?? 0.4;
    const latencyWeight = config.latencyWeight ?? 0.25;
    const costWeight = config.costWeight ?? 0.2;
    const errorWeight = config.errorWeight ?? 0.15;
    const total = successWeight + latencyWeight + costWeight + errorWeight;
    if (total <= 0) {
      throw new Error("at least one weight must be > 0");
    }
    this.successWeight = successWeight / total;
    this.latencyWeight = latencyWeight / total;
    this.costWeight = costWeight / total;
    this.errorWeight = errorWeight / total;
    this.maxLatencyMs = config.maxLatencyMs ?? 2000;
    this.maxCost = config.maxCost ?? 5;
    this.feedback = new Map();
  }

  chooseRoute(_context, routes, metrics = {}) {
    const eligible = routes.filter((route) => route.capacity > 0).sort((a, b) => a.name.localeCompare(b.name));
    if (eligible.length === 0) {
      throw new Error("no routes with positive capacity");
    }

    const scored = eligible.map((route) => [route, this.scoreRoute(route, this.resolveMetrics(route.name, metrics))]);
    scored.sort((a, b) => (b[1] - a[1]) || a[0].name.localeCompare(b[0].name));
    const confidence = scored.length === 1 ? 1 : clamp(scored[0][1] - scored[1][1]);
    return {
      selected_route: scored[0][0].name,
      score: Number(scored[0][1].toFixed(6)),
      confidence: Number(confidence.toFixed(6)),
    };
  }

  recordOutcome(routeName, success, latencyMs, _cost = null) {
    const state = this.feedback.get(routeName) || { observations: 0, successes: 0, avgLatency: 1000 };
    state.observations += 1;
    if (success) {
      state.successes += 1;
    }
    state.avgLatency += (latencyMs - state.avgLatency) / state.observations;
    this.feedback.set(routeName, state);
  }

  snapshotState() {
    const feedback = {};
    for (const [name, state] of this.feedback.entries()) {
      feedback[name] = { ...state };
    }
    return { feedback };
  }

  restoreState(state) {
    this.feedback = new Map();
    const feedback = (state && state.feedback) || {};
    Object.keys(feedback).forEach((name) => {
      this.feedback.set(name, {
        observations: Number(feedback[name].observations || 0),
        successes: Number(feedback[name].successes || 0),
        avgLatency: Number(feedback[name].avgLatency || 1000),
      });
    });
  }

  resolveMetrics(routeName, metrics) {
    if (metrics && metrics[routeName]) {
      return metrics[routeName];
    }
    if (this.feedback.has(routeName)) {
      const state = this.feedback.get(routeName);
      const successRate = state.observations > 0 ? state.successes / state.observations : 0.5;
      return {
        success_rate: successRate,
        error_rate: 1 - successRate,
        avg_latency: state.avgLatency,
        sample_size: state.observations,
      };
    }
    return { success_rate: 0.5, error_rate: 0.5, avg_latency: 1000, sample_size: 0 };
  }

  scoreRoute(route, metrics) {
    const success = clamp(metrics.success_rate ?? 0.5);
    const errorInv = 1 - clamp(metrics.error_rate ?? 0.5);
    const latencyInv = 1 - clamp((metrics.avg_latency ?? 1000) / this.maxLatencyMs);
    const costInv = 1 - clamp((route.cost ?? 0) / this.maxCost);
    return (
      this.successWeight * success +
      this.latencyWeight * latencyInv +
      this.costWeight * costInv +
      this.errorWeight * errorInv
    );
  }
}

class EpsilonBanditRouter extends BaseRoutingStrategy {
  constructor(config = {}) {
    super();
    this.epsilon = clamp(config.epsilon ?? 0.1);
    const successWeight = config.successWeight ?? 0.7;
    const latencyWeight = config.latencyWeight ?? 0.3;
    const total = successWeight + latencyWeight;
    if (total <= 0) {
      throw new Error("successWeight + latencyWeight must be > 0");
    }
    this.successWeight = successWeight / total;
    this.latencyWeight = latencyWeight / total;
    this.maxLatencyMs = config.maxLatencyMs ?? 2000;
    this.confidenceTrials = config.confidenceTrials ?? 300;
    this.seed = config.seed ?? 42;
    this.rng = new RNG(this.seed);
    this.state = new Map();
  }

  chooseRoute(_context, routes, _metrics = {}) {
    const eligible = routes.filter((route) => route.capacity > 0).map((route) => route.name).sort();
    if (eligible.length === 0) {
      throw new Error("no routes with positive capacity");
    }
    eligible.forEach((name) => {
      if (!this.state.has(name)) {
        this.state.set(name, { attempts: 0, estimatedReward: 0 });
      }
    });

    const selected = this.selectRoute(eligible, this.rng);
    const score = this.state.get(selected).estimatedReward;
    const confidence = this.estimateConfidence(selected, eligible);
    return {
      selected_route: selected,
      score: Number(score.toFixed(6)),
      confidence: Number(confidence.toFixed(6)),
    };
  }

  recordOutcome(routeName, success, latencyMs, _cost = null) {
    if (!this.state.has(routeName)) {
      this.state.set(routeName, { attempts: 0, estimatedReward: 0 });
    }
    const reward = this.successWeight * (success ? 1 : 0) + this.latencyWeight * (1 - clamp(latencyMs / this.maxLatencyMs));
    const state = this.state.get(routeName);
    state.attempts += 1;
    state.estimatedReward += (reward - state.estimatedReward) / state.attempts;
  }

  snapshotState() {
    const state = {};
    for (const [name, value] of this.state.entries()) {
      state[name] = { ...value };
    }
    return {
      epsilon: this.epsilon,
      successWeight: this.successWeight,
      latencyWeight: this.latencyWeight,
      maxLatencyMs: this.maxLatencyMs,
      seed: this.seed,
      state,
    };
  }

  restoreState(payload) {
    this.state = new Map();
    const state = (payload && payload.state) || {};
    Object.keys(state).forEach((name) => {
      this.state.set(name, {
        attempts: Number(state[name].attempts || 0),
        estimatedReward: Number(state[name].estimatedReward || 0),
      });
    });
  }

  selectRoute(routeNames, rng) {
    const unseen = routeNames.filter((name) => this.state.get(name).attempts === 0);
    if (unseen.length > 0) {
      return unseen[0];
    }
    if (rng.next() < this.epsilon) {
      return rng.choice(routeNames);
    }
    let bestRoute = routeNames[0];
    let bestScore = this.state.get(bestRoute).estimatedReward;
    for (const name of routeNames) {
      const score = this.state.get(name).estimatedReward;
      if (score > bestScore || (score === bestScore && name < bestRoute)) {
        bestScore = score;
        bestRoute = name;
      }
    }
    return bestRoute;
  }

  estimateConfidence(selectedRoute, routeNames) {
    const snapshot = routeNames
      .slice()
      .sort()
      .map((name) => `${name}:${this.state.get(name).attempts}:${this.state.get(name).estimatedReward.toFixed(8)}`)
      .join("|");
    const rng = new RNG(hashString(`${this.seed}|${snapshot}`));
    let wins = 0;
    for (let i = 0; i < this.confidenceTrials; i += 1) {
      if (this.selectRoute(routeNames, rng) === selectedRoute) {
        wins += 1;
      }
    }
    return wins / this.confidenceTrials;
  }
}

class ThompsonSamplingRouter extends BaseRoutingStrategy {
  constructor(config = {}) {
    super();
    this.priorAlpha = config.priorAlpha ?? 1;
    this.priorBeta = config.priorBeta ?? 1;
    this.latencyPenaltyWeight = config.latencyPenaltyWeight ?? 0.1;
    this.maxLatencyMs = config.maxLatencyMs ?? 2000;
    this.confidenceTrials = config.confidenceTrials ?? 400;
    this.seed = config.seed ?? 42;
    this.rng = new RNG(this.seed);
    this.state = new Map();
  }

  chooseRoute(_context, routes, metrics = {}) {
    const eligible = routes.filter((route) => route.capacity > 0).map((route) => route.name).sort();
    if (eligible.length === 0) {
      throw new Error("no routes with positive capacity");
    }
    eligible.forEach((name) => {
      if (!this.state.has(name)) {
        this.state.set(name, {
          alpha: this.priorAlpha,
          beta: this.priorBeta,
          attempts: 0,
          avgLatency: 1000,
        });
      }
    });

    const unseen = eligible.filter((name) => this.state.get(name).attempts === 0);
    if (unseen.length > 0) {
      const selected = unseen[0];
      const confidence = this.estimateConfidence(selected, eligible, metrics);
      return { selected_route: selected, score: 0.5, confidence: Number(confidence.toFixed(6)) };
    }

    let bestRoute = eligible[0];
    let bestScore = -1;
    for (const name of eligible) {
      const score = this.sampledScore(name, metrics, this.rng);
      if (score > bestScore || (score === bestScore && name < bestRoute)) {
        bestRoute = name;
        bestScore = score;
      }
    }
    const confidence = this.estimateConfidence(bestRoute, eligible, metrics);
    return {
      selected_route: bestRoute,
      score: Number(bestScore.toFixed(6)),
      confidence: Number(confidence.toFixed(6)),
    };
  }

  recordOutcome(routeName, success, latencyMs, _cost = null) {
    if (!this.state.has(routeName)) {
      this.state.set(routeName, {
        alpha: this.priorAlpha,
        beta: this.priorBeta,
        attempts: 0,
        avgLatency: 1000,
      });
    }
    const state = this.state.get(routeName);
    if (success) {
      state.alpha += 1;
    } else {
      state.beta += 1;
    }
    state.attempts += 1;
    state.avgLatency += (latencyMs - state.avgLatency) / state.attempts;
  }

  snapshotState() {
    const state = {};
    for (const [name, value] of this.state.entries()) {
      state[name] = { ...value };
    }
    return {
      priorAlpha: this.priorAlpha,
      priorBeta: this.priorBeta,
      latencyPenaltyWeight: this.latencyPenaltyWeight,
      maxLatencyMs: this.maxLatencyMs,
      seed: this.seed,
      state,
    };
  }

  restoreState(payload) {
    this.state = new Map();
    const state = (payload && payload.state) || {};
    Object.keys(state).forEach((name) => {
      this.state.set(name, {
        alpha: Number(state[name].alpha || this.priorAlpha),
        beta: Number(state[name].beta || this.priorBeta),
        attempts: Number(state[name].attempts || 0),
        avgLatency: Number(state[name].avgLatency || 1000),
      });
    });
  }

  sampledScore(routeName, metrics, rng) {
    const state = this.state.get(routeName);
    const sample = betaSample(state.alpha, state.beta, rng);
    const routeMetrics = metrics[routeName];
    const latency = routeMetrics ? routeMetrics.avg_latency : state.avgLatency;
    const penalty = this.latencyPenaltyWeight * clamp(latency / this.maxLatencyMs);
    return sample - penalty;
  }

  estimateConfidence(selectedRoute, routeNames, metrics) {
    const snapshot = routeNames
      .slice()
      .sort()
      .map((name) => {
        const state = this.state.get(name);
        return `${name}:${state.alpha.toFixed(6)}:${state.beta.toFixed(6)}:${state.attempts}`;
      })
      .join("|");
    const rng = new RNG(hashString(`${this.seed}|${snapshot}`));
    let wins = 0;
    for (let i = 0; i < this.confidenceTrials; i += 1) {
      const winner = this.simulateWinner(routeNames, metrics, rng);
      if (winner === selectedRoute) {
        wins += 1;
      }
    }
    return wins / this.confidenceTrials;
  }

  simulateWinner(routeNames, metrics, rng) {
    const unseen = routeNames.filter((name) => this.state.get(name).attempts === 0);
    if (unseen.length > 0) {
      return unseen[0];
    }
    let bestRoute = routeNames[0];
    let bestScore = -1;
    for (const name of routeNames) {
      const score = this.sampledScore(name, metrics, rng);
      if (score > bestScore || (score === bestScore && name < bestRoute)) {
        bestRoute = name;
        bestScore = score;
      }
    }
    return bestRoute;
  }
}

function registerStrategies(registry = StrategyRegistry) {
  registry.register("weighted", WeightedRouter, { overwrite: true });
  registry.register("bandit", EpsilonBanditRouter, { overwrite: true });
  registry.register("epsilon_bandit", EpsilonBanditRouter, { overwrite: true });
  registry.register("thompson", ThompsonSamplingRouter, { overwrite: true });
}

registerStrategies();

module.exports = {
  BaseRoutingStrategy,
  RouterEngine,
  StrategyRegistry,
  WeightedRouter,
  EpsilonBanditRouter,
  ThompsonSamplingRouter,
  registerStrategies,
};
