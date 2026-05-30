from services.ai.base import SummaryResult, AIProvider

def test_summary_result_quick_defaults():
    r = SummaryResult(
        title="Test",
        language="ko",
        word_count=100,
        reading_time_min=1,
        sections=[],
        summary="요약입니다.",
        key_points=["포인트1"],
        tags=["AI"],
        suggested_topic="AI/ML",
        summary_mode="quick",
    )
    assert r.insights is None
    assert r.summary_mode == "quick"

def test_summary_result_cost_usd_default():
    r = SummaryResult(
        title="T", language="en", word_count=0, reading_time_min=0,
        sections=[], summary="s", key_points=[], tags=[],
        suggested_topic="", summary_mode="quick",
    )
    assert r.cost_usd == 0.0

def test_ai_provider_is_abstract():
    import inspect
    assert inspect.isabstract(AIProvider)
