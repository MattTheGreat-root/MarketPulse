"""
Drill-down orchestration tests.

Verifies _category_stats adaptive behavior:
  * single-domain concentration triggers drill-down
  * axes picked by coverage + meaningful-buckets + balance gates
  * record shape (6 required keys) preserved across primary & drill views
  * primary view preserved for cross-profile comparisons
  * diverse shops keep the product-type breakdown
"""
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.analyzer import MarketAnalyzer  # noqa: E402


def _synthetic_df(rows):
    """Build a tiny DataFrame from [(description, price, engagement), ...].

    price_clean is normally derived in analyze_profile; we set it directly since
    _category_stats consumes it. Inputs are already clean numeric strings.
    """
    return pd.DataFrame({
        "description": [r[0] for r in rows],
        "price": [r[1] for r in rows],
        "price_clean": [float(r[1]) for r in rows],
        "engagement": [r[2] for r in rows],
        "post_index": list(range(1, len(rows) + 1)),
        "comments": [""] * len(rows),
    })


def test_all_sneakers_drills_by_brand():
    """All Sneakers, mixed brands → drills by brand with ≥2 buckets."""
    rows = [
        ("Air Max 90 سفید", "1200000", 50),
        ("Air Force 1 مشکی", "1300000", 60),
        ("Air Jordan طوسی", "1500000", 70),
        ("Vans Old Skool سیاه", "800000", 40),
        ("Vans Sk8-Hi سفید", "850000", 45),
        ("New Balance 550 خاکستری", "1100000", 55),
    ]
    analyzer = MarketAnalyzer()
    df = _synthetic_df(rows)
    df["category"] = analyzer._classify_products(df["description"])
    cats = analyzer._category_stats(df)

    assert cats["drilled"], "All-Sneakers shop should drill"
    assert cats["axis"] == "brand", f"Expected brand axis, got {cats['axis']}"
    assert len(cats["breakdown"]) >= 2, "Should have ≥2 brand buckets"
    # Primary view preserved
    assert "primary_breakdown" in cats
    assert cats["primary_breakdown"][0]["category"] == "Sneakers (کتونی)"


def test_mixed_shoe_types_drills():
    """Sneakers+Boots+Sandals (one domain, no category >60%) → drills."""
    rows = [
        ("Air Max مشکی", "1200000", 50),
        ("Air Force سفید", "1300000", 60),
        ("نیم بوت چرم مردانه", "2000000", 80),
        ("چکمه بلند زمستانی", "2500000", 90),
        ("صندل تابستانی مردانه", "400000", 30),
        ("دمپایی راحتی", "300000", 25),
    ]
    analyzer = MarketAnalyzer()
    df = _synthetic_df(rows)
    df["category"] = analyzer._classify_products(df["description"])
    cats = analyzer._category_stats(df)

    assert cats["drilled"], "Mixed Shoes (one domain) should drill"
    assert cats["domain"] == "Shoes"


def test_diverse_shop_no_drill():
    """Shoes+Bags+Jewelry (multi-domain) → no drill, keeps product breakdown."""
    rows = [
        ("Air Max سفید", "1200000", 50),
        ("نیم بوت چرم", "2000000", 80),
        ("کیف دستی زنانه چرم", "1500000", 70),
        ("کوله پشتی ضدآب", "900000", 40),
        ("گردنبند نقره", "800000", 60),
        ("انگشتر طلا", "3000000", 100),
    ]
    analyzer = MarketAnalyzer()
    df = _synthetic_df(rows)
    df["category"] = analyzer._classify_products(df["description"])
    cats = analyzer._category_stats(df)

    assert not cats["drilled"], "Diverse shop should NOT drill"
    assert cats["axis"] == "category"
    # breakdown == primary_breakdown when not drilled
    assert cats["breakdown"] == cats["primary_breakdown"]


def test_clothing_no_brands_drills_other_axis():
    """Single-domain Clothing with no brands → axis is NOT brand (gender/material/price)."""
    rows = [
        ("مانتو زنانه مشکی اداری", "1500000", 70),
        ("مانتو زنانه آبی مجلسی", "1800000", 80),
        ("شلوار جین مردانه آبی", "900000", 50),
        ("تیشرت نخی مردانه سفید", "400000", 30),
        ("شومیز زنانه یقه گرد", "600000", 40),
        ("کاپشن پافر مردانه", "2500000", 90),
    ]
    analyzer = MarketAnalyzer()
    df = _synthetic_df(rows)
    df["category"] = analyzer._classify_products(df["description"])
    cats = analyzer._category_stats(df)

    assert cats["drilled"], "Single-domain Clothing should drill"
    assert cats["axis"] != "brand", f"Expected non-brand axis, got {cats['axis']}"
    # Likely gender (مردانه/زنانه appear multiple times with coverage >50%)
    assert cats["axis"] in ("gender", "material", "price_band", "subtype")


def test_record_shape_invariant():
    """Every breakdown row has the 6 required keys, drilled or not."""
    rows = [
        ("Air Max 90", "1200000", 50),
        ("Air Force 1", "1300000", 60),
        ("Vans Old Skool", "800000", 40),
    ]
    analyzer = MarketAnalyzer()
    df = _synthetic_df(rows)
    df["category"] = analyzer._classify_products(df["description"])
    cats = analyzer._category_stats(df)

    required = {"category", "posts", "share_pct", "avg_engagement", "total_engagement", "avg_price"}
    for row in cats["breakdown"]:
        assert required.issubset(row.keys()), f"Missing keys in breakdown row: {row}"
    for row in cats["primary_breakdown"]:
        assert required.issubset(row.keys()), f"Missing keys in primary row: {row}"


def test_comparator_primary_view():
    """Drilled client + competitor → comparator uses primary_star_category/primary_breakdown."""
    rows_client = [
        ("Air Max مشکی Nike", "1200000", 50),
        ("Air Force Nike سفید", "1300000", 60),
        ("Air Jordan Nike طوسی", "1500000", 70),
        ("Vans Old Skool سیاه", "800000", 40),
        ("Vans Sk8-Hi سفید", "850000", 45),
    ]
    rows_comp = [
        ("کیف دستی چرم زنانه", "1500000", 70),
        ("کوله پشتی ضدآب", "900000", 45),
        ("گردنبند نقره", "800000", 60),
    ]
    analyzer = MarketAnalyzer()

    df_c = _synthetic_df(rows_client)
    df_c["category"] = analyzer._classify_products(df_c["description"])
    cats_c = analyzer._category_stats(df_c)

    df_comp = _synthetic_df(rows_comp)
    df_comp["category"] = analyzer._classify_products(df_comp["description"])
    cats_comp = analyzer._category_stats(df_comp)

    # Client drilled by brand, competitor did not → primary views differ
    assert cats_c.get("drilled"), "Client should drill"
    assert not cats_comp.get("drilled"), "Competitor should not drill"

    # Comparator logic: star_category read with fallback
    client_star = cats_c.get("primary_star_category") or cats_c.get("star_category")
    comp_star = cats_comp.get("primary_star_category") or cats_comp.get("star_category")

    # client_star should be a product type (Sneakers), not a brand (Nike)
    assert "Sneakers" in client_star or "کتونی" in client_star, \
        f"Primary star should be product type, got {client_star}"
    # competitor star should be a bag type
    assert comp_star in ["Handbag (کیف دستی)", "Backpack (کوله پشتی)"], \
        f"Competitor star should be bag, got {comp_star}"


def test_top_posts_relabeled_to_drill_axis():
    """When the mix drills by brand, top-post records carry the brand (not the
    generic product type) so section 7 matches the product-basket section."""
    rows = [
        ("Air Max 90 سفید نایک", "1200000", 50),
        ("Air Force 1 مشکی نایک", "1300000", 60),
        ("Air Jordan طوسی نایک", "1500000", 70),
        ("Vans Old Skool سیاه", "800000", 40),
        ("Vans Sk8-Hi سفید", "850000", 45),
        ("New Balance 550 خاکستری", "1100000", 55),
    ]
    analyzer = MarketAnalyzer()
    df = _synthetic_df(rows)
    df["category"] = analyzer._classify_products(df["description"])
    cats = analyzer._category_stats(df)
    assert cats["drilled"] and cats["axis"] == "brand"

    records = analyzer._posts_to_records(df, cats, df)
    labels = {r["category"] for r in records}
    # Brands, not the generic "Sneakers (کتونی)" product type.
    assert labels & {"Nike", "Vans", "New Balance"}, f"expected brands, got {labels}"
    assert "Sneakers (کتونی)" not in labels, "should not show generic product type"


def test_top_posts_fallback_when_not_drilled():
    """A diverse (non-drilled) shop keeps the product-type label on top posts."""
    rows = [
        ("Air Max سفید", "1200000", 50),
        ("نیم بوت چرم", "2000000", 80),
        ("کیف دستی زنانه چرم", "1500000", 70),
        ("گردنبند نقره", "800000", 60),
    ]
    analyzer = MarketAnalyzer()
    df = _synthetic_df(rows)
    df["category"] = analyzer._classify_products(df["description"])
    cats = analyzer._category_stats(df)
    assert not cats["drilled"]

    records = analyzer._posts_to_records(df, cats, df)
    # Falls back to each post's own product-type category.
    cats_seen = {r["category"] for r in records}
    assert any("کیف" in c or "گردنبند" in c or "بوت" in c or "کتونی" in c for c in cats_seen)


def run():
    tests = [
        test_all_sneakers_drills_by_brand,
        test_mixed_shoe_types_drills,
        test_diverse_shop_no_drill,
        test_clothing_no_brands_drills_other_axis,
        test_record_shape_invariant,
        test_comparator_primary_view,
        test_top_posts_relabeled_to_drill_axis,
        test_top_posts_fallback_when_not_drilled,
    ]
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
