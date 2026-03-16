package smartrouter

import (
	"errors"
	"fmt"
	"hash/fnv"
	"math"
	"math/rand"
	"sort"
	"strings"
	"sync"
)

type PaymentContext struct {
	Amount        float64 `json:"amount"`
	PaymentMethod string  `json:"payment_method"`
	PayerBank     string  `json:"payer_bank"`
	Region        string  `json:"region"`
	Timestamp     string  `json:"timestamp"`
}

type RouteDefinition struct {
	Name     string  `json:"name"`
	Cost     float64 `json:"cost"`
	Capacity float64 `json:"capacity"`
}

type RouteMetrics struct {
	SuccessRate float64 `json:"success_rate"`
	ErrorRate   float64 `json:"error_rate"`
	AvgLatency  float64 `json:"avg_latency"`
	SampleSize  int     `json:"sample_size"`
}

type RoutingDecision struct {
	SelectedRoute string  `json:"selected_route"`
	Score         float64 `json:"score"`
	Confidence    float64 `json:"confidence"`
}

type RoutingStrategy interface {
	ChooseRoute(ctx PaymentContext, routes []RouteDefinition, metrics map[string]RouteMetrics) (RoutingDecision, error)
	RecordOutcome(routeName string, success bool, latencyMs float64, cost *float64)
	SnapshotState() map[string]any
	RestoreState(state map[string]any) error
}

type RouterEngine struct {
	strategy RoutingStrategy
}

func NewRouterEngine(strategy RoutingStrategy) (*RouterEngine, error) {
	if strategy == nil {
		return nil, errors.New("strategy must not be nil")
	}
	return &RouterEngine{strategy: strategy}, nil
}

func (r *RouterEngine) Route(
	ctx PaymentContext,
	routes []RouteDefinition,
	metrics map[string]RouteMetrics,
) (RoutingDecision, error) {
	if len(routes) == 0 {
		return RoutingDecision{}, errors.New("routes must not be empty")
	}
	decision, err := r.strategy.ChooseRoute(ctx, routes, metrics)
	if err != nil {
		return RoutingDecision{}, err
	}
	if decision.Confidence < 0 || decision.Confidence > 1 {
		return RoutingDecision{}, errors.New("strategy returned confidence outside [0,1]")
	}
	return decision, nil
}

func (r *RouterEngine) RecordOutcome(routeName string, success bool, latencyMs float64, cost *float64) {
	r.strategy.RecordOutcome(routeName, success, latencyMs, cost)
}

func (r *RouterEngine) SnapshotState() map[string]any {
	return r.strategy.SnapshotState()
}

func (r *RouterEngine) RestoreState(state map[string]any) error {
	return r.strategy.RestoreState(state)
}

func NewRouterEngineFromRegistry(name string, config map[string]any) (*RouterEngine, error) {
	strategy, err := CreateStrategy(name, config)
	if err != nil {
		return nil, err
	}
	return NewRouterEngine(strategy)
}

type StrategyFactory func(config map[string]any) (RoutingStrategy, error)

var (
	registryMu       sync.RWMutex
	strategyRegistry = map[string]StrategyFactory{}
)

func RegisterStrategy(name string, factory StrategyFactory, overwrite bool) error {
	key := strings.ToLower(strings.TrimSpace(name))
	if key == "" {
		return errors.New("strategy name must not be empty")
	}
	registryMu.Lock()
	defer registryMu.Unlock()
	if !overwrite {
		if _, exists := strategyRegistry[key]; exists {
			return fmt.Errorf("strategy '%s' already registered", key)
		}
	}
	strategyRegistry[key] = factory
	return nil
}

func CreateStrategy(name string, config map[string]any) (RoutingStrategy, error) {
	key := strings.ToLower(strings.TrimSpace(name))
	registryMu.RLock()
	factory, exists := strategyRegistry[key]
	registryMu.RUnlock()
	if !exists {
		return nil, fmt.Errorf("strategy '%s' is not registered", key)
	}
	return factory(config)
}

func ListStrategies() []string {
	registryMu.RLock()
	defer registryMu.RUnlock()
	keys := make([]string, 0, len(strategyRegistry))
	for key := range strategyRegistry {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

type weightedFeedback struct {
	Observations int
	Successes    int
	AvgLatency   float64
}

type WeightedRouter struct {
	SuccessWeight float64
	LatencyWeight float64
	CostWeight    float64
	ErrorWeight   float64
	MaxLatencyMs  float64
	MaxCost       float64
	Feedback      map[string]*weightedFeedback
}

func NewWeightedRouter(config map[string]any) *WeightedRouter {
	successWeight := getFloat(config, "success_weight", 0.40)
	latencyWeight := getFloat(config, "latency_weight", 0.25)
	costWeight := getFloat(config, "cost_weight", 0.20)
	errorWeight := getFloat(config, "error_weight", 0.15)
	total := successWeight + latencyWeight + costWeight + errorWeight
	if total <= 0 {
		total = 1.0
		successWeight, latencyWeight, costWeight, errorWeight = 0.40, 0.25, 0.20, 0.15
	}
	return &WeightedRouter{
		SuccessWeight: successWeight / total,
		LatencyWeight: latencyWeight / total,
		CostWeight:    costWeight / total,
		ErrorWeight:   errorWeight / total,
		MaxLatencyMs:  getFloat(config, "max_latency_ms", 2000.0),
		MaxCost:       getFloat(config, "max_cost", 5.0),
		Feedback:      map[string]*weightedFeedback{},
	}
}

func (w *WeightedRouter) ChooseRoute(
	_ PaymentContext,
	routes []RouteDefinition,
	metrics map[string]RouteMetrics,
) (RoutingDecision, error) {
	eligible := make([]RouteDefinition, 0, len(routes))
	for _, route := range routes {
		if route.Capacity > 0 {
			eligible = append(eligible, route)
		}
	}
	if len(eligible) == 0 {
		return RoutingDecision{}, errors.New("no routes with positive capacity")
	}
	sort.Slice(eligible, func(i, j int) bool {
		return eligible[i].Name < eligible[j].Name
	})

	type routeScore struct {
		Name  string
		Score float64
	}
	scored := make([]routeScore, 0, len(eligible))
	for _, route := range eligible {
		routeMetrics := w.resolveMetrics(route.Name, metrics)
		success := clamp01(routeMetrics.SuccessRate)
		errorInv := 1.0 - clamp01(routeMetrics.ErrorRate)
		latencyInv := 1.0 - clamp01(routeMetrics.AvgLatency/w.MaxLatencyMs)
		costInv := 1.0 - clamp01(route.Cost/w.MaxCost)
		score := (w.SuccessWeight * success) +
			(w.LatencyWeight * latencyInv) +
			(w.CostWeight * costInv) +
			(w.ErrorWeight * errorInv)
		scored = append(scored, routeScore{Name: route.Name, Score: score})
	}

	sort.Slice(scored, func(i, j int) bool {
		if scored[i].Score == scored[j].Score {
			return scored[i].Name < scored[j].Name
		}
		return scored[i].Score > scored[j].Score
	})
	confidence := 1.0
	if len(scored) > 1 {
		confidence = clamp01(scored[0].Score - scored[1].Score)
	}
	return RoutingDecision{
		SelectedRoute: scored[0].Name,
		Score:         round6(scored[0].Score),
		Confidence:    round6(confidence),
	}, nil
}

func (w *WeightedRouter) RecordOutcome(routeName string, success bool, latencyMs float64, _ *float64) {
	state, exists := w.Feedback[routeName]
	if !exists {
		state = &weightedFeedback{AvgLatency: 1000.0}
		w.Feedback[routeName] = state
	}
	state.Observations++
	if success {
		state.Successes++
	}
	state.AvgLatency += (latencyMs - state.AvgLatency) / float64(state.Observations)
}

func (w *WeightedRouter) SnapshotState() map[string]any {
	out := map[string]any{"feedback": map[string]any{}}
	feedback := out["feedback"].(map[string]any)
	for route, state := range w.Feedback {
		feedback[route] = map[string]any{
			"observations": state.Observations,
			"successes":    state.Successes,
			"avg_latency":  state.AvgLatency,
		}
	}
	return out
}

func (w *WeightedRouter) RestoreState(state map[string]any) error {
	w.Feedback = map[string]*weightedFeedback{}
	rawFeedback, ok := state["feedback"].(map[string]any)
	if !ok {
		return nil
	}
	for route, rawState := range rawFeedback {
		row, castOK := rawState.(map[string]any)
		if !castOK {
			continue
		}
		w.Feedback[route] = &weightedFeedback{
			Observations: getInt(row, "observations", 0),
			Successes:    getInt(row, "successes", 0),
			AvgLatency:   getFloat(row, "avg_latency", 1000.0),
		}
	}
	return nil
}

func (w *WeightedRouter) resolveMetrics(name string, metrics map[string]RouteMetrics) RouteMetrics {
	if metrics != nil {
		if metric, ok := metrics[name]; ok {
			return metric
		}
	}
	if feedback, ok := w.Feedback[name]; ok && feedback.Observations > 0 {
		successRate := float64(feedback.Successes) / float64(feedback.Observations)
		return RouteMetrics{
			SuccessRate: successRate,
			ErrorRate:   1.0 - successRate,
			AvgLatency:  feedback.AvgLatency,
			SampleSize:  feedback.Observations,
		}
	}
	return RouteMetrics{SuccessRate: 0.5, ErrorRate: 0.5, AvgLatency: 1000.0, SampleSize: 0}
}

type banditState struct {
	Attempts        int
	EstimatedReward float64
}

type EpsilonBanditRouter struct {
	Epsilon          float64
	SuccessWeight    float64
	LatencyWeight    float64
	MaxLatencyMs     float64
	ConfidenceTrials int
	Seed             int64
	Rng              *rand.Rand
	State            map[string]*banditState
}

func NewEpsilonBanditRouter(config map[string]any) *EpsilonBanditRouter {
	epsilon := clamp01(getFloat(config, "epsilon", 0.10))
	successWeight := getFloat(config, "success_weight", 0.70)
	latencyWeight := getFloat(config, "latency_weight", 0.30)
	total := successWeight + latencyWeight
	if total <= 0 {
		total = 1.0
		successWeight, latencyWeight = 0.70, 0.30
	}
	seed := int64(getInt(config, "seed", 42))
	return &EpsilonBanditRouter{
		Epsilon:          epsilon,
		SuccessWeight:    successWeight / total,
		LatencyWeight:    latencyWeight / total,
		MaxLatencyMs:     getFloat(config, "max_latency_ms", 2000.0),
		ConfidenceTrials: getInt(config, "confidence_trials", 300),
		Seed:             seed,
		Rng:              rand.New(rand.NewSource(seed)),
		State:            map[string]*banditState{},
	}
}

func (e *EpsilonBanditRouter) ChooseRoute(
	_ PaymentContext,
	routes []RouteDefinition,
	_ map[string]RouteMetrics,
) (RoutingDecision, error) {
	routeNames := make([]string, 0, len(routes))
	for _, route := range routes {
		if route.Capacity > 0 {
			routeNames = append(routeNames, route.Name)
		}
	}
	if len(routeNames) == 0 {
		return RoutingDecision{}, errors.New("no routes with positive capacity")
	}
	sort.Strings(routeNames)
	e.ensureRoutes(routeNames)

	selected := e.selectRoute(routeNames, e.Rng)
	score := e.State[selected].EstimatedReward
	confidence := e.estimateConfidence(selected, routeNames)

	return RoutingDecision{
		SelectedRoute: selected,
		Score:         round6(score),
		Confidence:    round6(confidence),
	}, nil
}

func (e *EpsilonBanditRouter) RecordOutcome(routeName string, success bool, latencyMs float64, _ *float64) {
	e.ensureRoutes([]string{routeName})
	reward := e.SuccessWeight*boolToFloat(success) + e.LatencyWeight*(1.0-clamp01(latencyMs/e.MaxLatencyMs))
	state := e.State[routeName]
	state.Attempts++
	state.EstimatedReward += (reward - state.EstimatedReward) / float64(state.Attempts)
}

func (e *EpsilonBanditRouter) SnapshotState() map[string]any {
	out := map[string]any{"state": map[string]any{}}
	state := out["state"].(map[string]any)
	for route, value := range e.State {
		state[route] = map[string]any{
			"attempts":         value.Attempts,
			"estimated_reward": value.EstimatedReward,
		}
	}
	return out
}

func (e *EpsilonBanditRouter) RestoreState(state map[string]any) error {
	e.State = map[string]*banditState{}
	rawState, ok := state["state"].(map[string]any)
	if !ok {
		return nil
	}
	for route, rawRow := range rawState {
		row, castOK := rawRow.(map[string]any)
		if !castOK {
			continue
		}
		e.State[route] = &banditState{
			Attempts:        getInt(row, "attempts", 0),
			EstimatedReward: getFloat(row, "estimated_reward", 0.0),
		}
	}
	return nil
}

func (e *EpsilonBanditRouter) ensureRoutes(routeNames []string) {
	for _, route := range routeNames {
		if _, exists := e.State[route]; !exists {
			e.State[route] = &banditState{}
		}
	}
}

func (e *EpsilonBanditRouter) selectRoute(routeNames []string, rng *rand.Rand) string {
	for _, route := range routeNames {
		if e.State[route].Attempts == 0 {
			return route
		}
	}
	if rng.Float64() < e.Epsilon {
		return routeNames[rng.Intn(len(routeNames))]
	}
	best := routeNames[0]
	bestScore := e.State[best].EstimatedReward
	for _, route := range routeNames[1:] {
		score := e.State[route].EstimatedReward
		if score > bestScore || (score == bestScore && route < best) {
			best = route
			bestScore = score
		}
	}
	return best
}

func (e *EpsilonBanditRouter) estimateConfidence(selected string, routeNames []string) float64 {
	seed := stableBanditSeed(e.Seed, routeNames, e.State)
	rng := rand.New(rand.NewSource(seed))
	wins := 0
	for i := 0; i < e.ConfidenceTrials; i++ {
		if e.selectRoute(routeNames, rng) == selected {
			wins++
		}
	}
	return float64(wins) / float64(e.ConfidenceTrials)
}

type thompsonState struct {
	Alpha      float64
	Beta       float64
	Attempts   int
	AvgLatency float64
}

type ThompsonSamplingRouter struct {
	PriorAlpha          float64
	PriorBeta           float64
	LatencyPenalty      float64
	MaxLatencyMs        float64
	ConfidenceTrials    int
	Seed                int64
	Rng                 *rand.Rand
	State               map[string]*thompsonState
}

func NewThompsonSamplingRouter(config map[string]any) *ThompsonSamplingRouter {
	seed := int64(getInt(config, "seed", 42))
	return &ThompsonSamplingRouter{
		PriorAlpha:       getFloat(config, "prior_alpha", 1.0),
		PriorBeta:        getFloat(config, "prior_beta", 1.0),
		LatencyPenalty:   getFloat(config, "latency_penalty_weight", 0.10),
		MaxLatencyMs:     getFloat(config, "max_latency_ms", 2000.0),
		ConfidenceTrials: getInt(config, "confidence_trials", 400),
		Seed:             seed,
		Rng:              rand.New(rand.NewSource(seed)),
		State:            map[string]*thompsonState{},
	}
}

func (t *ThompsonSamplingRouter) ChooseRoute(
	_ PaymentContext,
	routes []RouteDefinition,
	metrics map[string]RouteMetrics,
) (RoutingDecision, error) {
	routeNames := make([]string, 0, len(routes))
	for _, route := range routes {
		if route.Capacity > 0 {
			routeNames = append(routeNames, route.Name)
		}
	}
	if len(routeNames) == 0 {
		return RoutingDecision{}, errors.New("no routes with positive capacity")
	}
	sort.Strings(routeNames)
	t.ensureRoutes(routeNames)

	for _, route := range routeNames {
		if t.State[route].Attempts == 0 {
			confidence := t.estimateConfidence(route, routeNames, metrics)
			return RoutingDecision{
				SelectedRoute: route,
				Score:         0.5,
				Confidence:    round6(confidence),
			}, nil
		}
	}

	bestRoute := routeNames[0]
	bestScore := -1.0
	for _, route := range routeNames {
		score := t.sampledScore(route, metrics, t.Rng)
		if score > bestScore || (score == bestScore && route < bestRoute) {
			bestScore = score
			bestRoute = route
		}
	}
	confidence := t.estimateConfidence(bestRoute, routeNames, metrics)
	return RoutingDecision{
		SelectedRoute: bestRoute,
		Score:         round6(bestScore),
		Confidence:    round6(confidence),
	}, nil
}

func (t *ThompsonSamplingRouter) RecordOutcome(routeName string, success bool, latencyMs float64, _ *float64) {
	t.ensureRoutes([]string{routeName})
	state := t.State[routeName]
	if success {
		state.Alpha++
	} else {
		state.Beta++
	}
	state.Attempts++
	state.AvgLatency += (latencyMs - state.AvgLatency) / float64(state.Attempts)
}

func (t *ThompsonSamplingRouter) SnapshotState() map[string]any {
	out := map[string]any{"state": map[string]any{}}
	state := out["state"].(map[string]any)
	for route, value := range t.State {
		state[route] = map[string]any{
			"alpha":       value.Alpha,
			"beta":        value.Beta,
			"attempts":    value.Attempts,
			"avg_latency": value.AvgLatency,
		}
	}
	return out
}

func (t *ThompsonSamplingRouter) RestoreState(state map[string]any) error {
	t.State = map[string]*thompsonState{}
	rawState, ok := state["state"].(map[string]any)
	if !ok {
		return nil
	}
	for route, rawRow := range rawState {
		row, castOK := rawRow.(map[string]any)
		if !castOK {
			continue
		}
		t.State[route] = &thompsonState{
			Alpha:      getFloat(row, "alpha", t.PriorAlpha),
			Beta:       getFloat(row, "beta", t.PriorBeta),
			Attempts:   getInt(row, "attempts", 0),
			AvgLatency: getFloat(row, "avg_latency", 1000.0),
		}
	}
	return nil
}

func (t *ThompsonSamplingRouter) ensureRoutes(routeNames []string) {
	for _, route := range routeNames {
		if _, exists := t.State[route]; !exists {
			t.State[route] = &thompsonState{
				Alpha:      t.PriorAlpha,
				Beta:       t.PriorBeta,
				AvgLatency: 1000.0,
			}
		}
	}
}

func (t *ThompsonSamplingRouter) sampledScore(
	routeName string,
	metrics map[string]RouteMetrics,
	rng *rand.Rand,
) float64 {
	state := t.State[routeName]
	sample := betaSample(state.Alpha, state.Beta, rng)
	latency := state.AvgLatency
	if metric, ok := metrics[routeName]; ok {
		latency = metric.AvgLatency
	}
	penalty := t.LatencyPenalty * clamp01(latency/t.MaxLatencyMs)
	return sample - penalty
}

func (t *ThompsonSamplingRouter) estimateConfidence(
	selected string,
	routeNames []string,
	metrics map[string]RouteMetrics,
) float64 {
	seed := stableThompsonSeed(t.Seed, routeNames, t.State, metrics)
	rng := rand.New(rand.NewSource(seed))
	wins := 0
	for i := 0; i < t.ConfidenceTrials; i++ {
		if t.simulateWinner(routeNames, metrics, rng) == selected {
			wins++
		}
	}
	return float64(wins) / float64(t.ConfidenceTrials)
}

func (t *ThompsonSamplingRouter) simulateWinner(
	routeNames []string,
	metrics map[string]RouteMetrics,
	rng *rand.Rand,
) string {
	for _, route := range routeNames {
		if t.State[route].Attempts == 0 {
			return route
		}
	}
	bestRoute := routeNames[0]
	bestScore := -1.0
	for _, route := range routeNames {
		score := t.sampledScore(route, metrics, rng)
		if score > bestScore || (score == bestScore && route < bestRoute) {
			bestScore = score
			bestRoute = route
		}
	}
	return bestRoute
}

func betaSample(alpha float64, beta float64, rng *rand.Rand) float64 {
	x := gammaSample(alpha, rng)
	y := gammaSample(beta, rng)
	return x / (x + y)
}

func gammaSample(shape float64, rng *rand.Rand) float64 {
	if shape <= 0 {
		panic("gamma shape must be > 0")
	}
	if shape < 1 {
		return gammaSample(shape+1, rng) * math.Pow(rng.Float64(), 1.0/shape)
	}
	d := shape - 1.0/3.0
	c := 1.0 / math.Sqrt(9*d)
	for {
		x := rng.NormFloat64()
		v := math.Pow(1+c*x, 3)
		if v <= 0 {
			continue
		}
		u := rng.Float64()
		if u < 1-0.0331*math.Pow(x, 4) {
			return d * v
		}
		if math.Log(u) < 0.5*x*x+d*(1-v+math.Log(v)) {
			return d * v
		}
	}
}

func stableBanditSeed(seed int64, routeNames []string, state map[string]*banditState) int64 {
	hasher := fnv.New64a()
	_, _ = hasher.Write([]byte(fmt.Sprintf("%d", seed)))
	_, _ = hasher.Write([]byte(strings.Join(routeNames, ",")))
	keys := make([]string, 0, len(state))
	for key := range state {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		row := state[key]
		_, _ = hasher.Write([]byte(fmt.Sprintf("|%s:%d:%0.8f", key, row.Attempts, row.EstimatedReward)))
	}
	return int64(hasher.Sum64())
}

func stableThompsonSeed(
	seed int64,
	routeNames []string,
	state map[string]*thompsonState,
	metrics map[string]RouteMetrics,
) int64 {
	hasher := fnv.New64a()
	_, _ = hasher.Write([]byte(fmt.Sprintf("%d", seed)))
	_, _ = hasher.Write([]byte(strings.Join(routeNames, ",")))
	keys := make([]string, 0, len(state))
	for key := range state {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		row := state[key]
		_, _ = hasher.Write([]byte(fmt.Sprintf("|%s:%0.4f:%0.4f:%d:%0.4f", key, row.Alpha, row.Beta, row.Attempts, row.AvgLatency)))
	}
	metricKeys := make([]string, 0, len(metrics))
	for key := range metrics {
		metricKeys = append(metricKeys, key)
	}
	sort.Strings(metricKeys)
	for _, key := range metricKeys {
		row := metrics[key]
		_, _ = hasher.Write([]byte(fmt.Sprintf("|%s:%0.4f:%0.4f", key, row.SuccessRate, row.AvgLatency)))
	}
	return int64(hasher.Sum64())
}

func clamp01(value float64) float64 {
	if value < 0 {
		return 0
	}
	if value > 1 {
		return 1
	}
	return value
}

func round6(value float64) float64 {
	return math.Round(value*1_000_000) / 1_000_000
}

func boolToFloat(value bool) float64 {
	if value {
		return 1.0
	}
	return 0.0
}

func getFloat(source map[string]any, key string, fallback float64) float64 {
	if source == nil {
		return fallback
	}
	raw, exists := source[key]
	if !exists {
		return fallback
	}
	switch value := raw.(type) {
	case float64:
		return value
	case float32:
		return float64(value)
	case int:
		return float64(value)
	case int64:
		return float64(value)
	case int32:
		return float64(value)
	default:
		return fallback
	}
}

func getInt(source map[string]any, key string, fallback int) int {
	if source == nil {
		return fallback
	}
	raw, exists := source[key]
	if !exists {
		return fallback
	}
	switch value := raw.(type) {
	case int:
		return value
	case int64:
		return int(value)
	case int32:
		return int(value)
	case float64:
		return int(value)
	case float32:
		return int(value)
	default:
		return fallback
	}
}

func init() {
	if err := RegisterStrategy("weighted", func(config map[string]any) (RoutingStrategy, error) {
		return NewWeightedRouter(config), nil
	}, true); err != nil {
		panic(err)
	}
	if err := RegisterStrategy("bandit", func(config map[string]any) (RoutingStrategy, error) {
		return NewEpsilonBanditRouter(config), nil
	}, true); err != nil {
		panic(err)
	}
	if err := RegisterStrategy("epsilon_bandit", func(config map[string]any) (RoutingStrategy, error) {
		return NewEpsilonBanditRouter(config), nil
	}, true); err != nil {
		panic(err)
	}
	if err := RegisterStrategy("thompson", func(config map[string]any) (RoutingStrategy, error) {
		return NewThompsonSamplingRouter(config), nil
	}, true); err != nil {
		panic(err)
	}
}
