"""
Owner-recommendations tests.

The full report used to emit strategic advice ONLY when a competitor was
supplied (the advice list was 100% competitor-derived). A solo report got an
empty advice section. ReportGenerator._recommendations now derives concrete,
prioritized actions from the shop's OWN insights, so:
  * a solo report always yields a non-trivial, deduped action list
  * the list reacts to real signals (declining momentum, hidden prices,
    buyer-intent comments) and never renders empty
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.report_generator import ReportGenerator  # noqa: E402


def _insights(**over):
    """Minimal client-insights dict shaped like MarketAnalyzer output."""
    base = {
        "username": "shop",
        "post_count": 40,
        "engagement": {"mean": 500, "median": 400, "total": 20000, "max": 3000, "min": 10, "std": 300},
        "categories": {
            "star_category": "Nike", "underperformer": "Vans",
            "axis_label_fa": "برند", "drilled": True, "axis": "brand",
        },
        "pricing": {"available": True, "best_selling_band": "4M+",
                    "count_unpriced": 2, "count_outliers_removed": 0},
        "momentum": {"available": True, "growth_pct": -56.9, "trend": "declining"},
        "demand_signals": {"price_questions": 0, "order_intents": 0, "complaints": 0},
        "hashtags": {"most_used": [], "top_performing": []},
    }
    base.update(over)
    return base


def test_solo_report_has_recommendations():
    """No competitor, no comparison → still a substantial action list."""
    rg = ReportGenerator(output_dir=os.path.join(os.path.dirname(__file__), "_out"))
    recs = rg._recommendations(_insights())
    assert len(recs) >= 5, f"expected a full list, got {len(recs)}"
    # section renders with numbered advice cards
    html = rg._recommendations_section(_insights())
    assert "advice-card" in html and "توصیه" in html


def test_reacts_to_signals():
    """Declining momentum, hidden prices, and price questions each surface."""
    rg = ReportGenerator(output_dir=os.path.join(os.path.dirname(__file__), "_out"))
    ins = _insights(
        pricing={"available": True, "best_selling_band": "4M+", "count_unpriced": 25},
        demand_signals={"price_questions": 8, "order_intents": 3, "complaints": 1},
    )
    joined = " ".join(rg._recommendations(ins))
    assert "افت" in joined, "declining momentum advice missing"
    assert "قیمت مشخص ندارند" in joined, "hidden-price advice missing"
    assert "پرسش قیمت" in joined, "buyer-question advice missing"


def test_never_empty_minimal_data():
    """Even with almost no signals the evergreen backfill keeps it useful."""
    rg = ReportGenerator(output_dir=os.path.join(os.path.dirname(__file__), "_out"))
    ins = _insights(
        categories={}, pricing={"available": False},
        momentum={"available": False}, hashtags={"most_used": [], "top_performing": []},
        demand_signals={"price_questions": 0, "order_intents": 0, "complaints": 0},
    )
    recs = rg._recommendations(ins)
    assert len(recs) >= 3, f"evergreen backfill should apply, got {len(recs)}"


def run():
    tests = [test_solo_report_has_recommendations, test_reacts_to_signals,
             test_never_empty_minimal_data]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"[ERROR] {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
