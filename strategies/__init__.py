"""Built-in routing strategy implementations."""

from core.strategy_registry import StrategyRegistry
from strategies.contextual_bandit_router import ContextualBanditRouter
from strategies.epsilon_bandit_router import EpsilonBanditRouter
from strategies.predictive_failure_router import PredictiveFailureRouter
from strategies.thompson_sampling_router import ThompsonSamplingRouter
from strategies.weighted_router import WeightedRouter

StrategyRegistry.register("weighted", WeightedRouter, overwrite=True)
StrategyRegistry.register("bandit", EpsilonBanditRouter, overwrite=True)
StrategyRegistry.register("epsilon_bandit", EpsilonBanditRouter, overwrite=True)
StrategyRegistry.register("thompson", ThompsonSamplingRouter, overwrite=True)
StrategyRegistry.register("contextual_bandit", ContextualBanditRouter, overwrite=True)
StrategyRegistry.register("predictive_failure", PredictiveFailureRouter, overwrite=True)

__all__ = [
    "WeightedRouter",
    "EpsilonBanditRouter",
    "ThompsonSamplingRouter",
    "ContextualBanditRouter",
    "PredictiveFailureRouter",
]
