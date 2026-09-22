from weatherml.ml.registry import decide_promotion


def test_bootstrap_promotes_when_no_production_model():
    decision = decide_promotion(candidate_mae=1.0, baseline_mae=2.0, production_mae=None)
    assert decision.promote is True
    assert "bootstrap" in decision.reason


def test_refuses_promotion_if_worse_than_baseline():
    decision = decide_promotion(candidate_mae=2.5, baseline_mae=2.0, production_mae=None)
    assert decision.promote is False
    assert "baseline" in decision.reason


def test_refuses_promotion_if_equal_to_baseline():
    decision = decide_promotion(candidate_mae=2.0, baseline_mae=2.0, production_mae=None)
    assert decision.promote is False


def test_promotes_when_meaningfully_better_than_production():
    decision = decide_promotion(
        candidate_mae=1.0, baseline_mae=3.0, production_mae=1.5, improvement_threshold=0.02
    )
    assert decision.promote is True


def test_refuses_when_improvement_below_threshold():
    # 1.0 vs 1.005 production is only a 0.5% improvement, below the 2% bar
    decision = decide_promotion(
        candidate_mae=1.0, baseline_mae=3.0, production_mae=1.005, improvement_threshold=0.02
    )
    assert decision.promote is False
    assert "does not sufficiently beat" in decision.reason


def test_refuses_when_tied_with_production():
    decision = decide_promotion(
        candidate_mae=0.949, baseline_mae=1.4, production_mae=0.949, improvement_threshold=0.02
    )
    assert decision.promote is False


def test_promotes_exactly_at_threshold_boundary():
    # production_mae=1.0, threshold=0.02 -> required <= 0.98
    decision = decide_promotion(
        candidate_mae=0.98, baseline_mae=2.0, production_mae=1.0, improvement_threshold=0.02
    )
    assert decision.promote is True
