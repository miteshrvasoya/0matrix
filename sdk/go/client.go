package smartrouter

func NewWeightedRouterDefault() *WeightedRouter {
	return NewWeightedRouter(nil)
}

func NewEpsilonBanditRouterDefault() *EpsilonBanditRouter {
	return NewEpsilonBanditRouter(nil)
}

func NewThompsonSamplingRouterDefault() *ThompsonSamplingRouter {
	return NewThompsonSamplingRouter(nil)
}

func MustNewRouterEngine(strategy RoutingStrategy) *RouterEngine {
	engine, err := NewRouterEngine(strategy)
	if err != nil {
		panic(err)
	}
	return engine
}

func Float64Ptr(value float64) *float64 {
	return &value
}
