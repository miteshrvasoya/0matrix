from __future__ import annotations

from smart_router._bootstrap import ensure_repo_root_on_path

ensure_repo_root_on_path()

from strategies.contextual_bandit_router import ContextualBanditRouter
from strategies.epsilon_bandit_router import EpsilonBanditRouter
from strategies.predictive_failure_router import PredictiveFailureRouter
from strategies.thompson_sampling_router import ThompsonSamplingRouter
from strategies.weighted_router import WeightedRouter

__all__ = [
    "WeightedRouter",
    "EpsilonBanditRouter",
    "ThompsonSamplingRouter",
    "ContextualBanditRouter",
    "PredictiveFailureRouter",
]
