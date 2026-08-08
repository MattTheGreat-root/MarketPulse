"""
Pricing-hygiene tests.

Verifies _pricing_stats no longer counts discount/promo posts as products and
trims price outliers:
  * promo posts (discount amount parsed as price) are excluded
  * a real product post that merely carries a "کد تخفیف" is kept
  * a lone extreme price is trimmed by the IQR fence
"""
import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.analyzer import MarketAnalyzer  # noqa: E402


def _priced_df(rows):
    """Build a frame from [(description, price), ...] mirroring analyze_profile:
    clean the price, flag promo posts, null their price_clean."""
    a = MarketAnalyzer()
    df = pd.DataFrame({
        "description": [r[0] for r in rows],
        "price": [r[1] for r in rows],
        "engagement": [10] * len(rows),
        "post_index": list(range(1, len(rows) + 1)),
    })
    df["price_clean"] = a._clean_price_series(df["price"])
    df["is_promo"] = a._promo_mask(df["description"])
    df.loc[df["is_promo"], "price_clean"] = np.nan
    return a, df


def test_promo_post_excluded_real_kept():
    """Discount-amount posts drop out; a real product with a discount code stays."""
    rows = [
        ("مبلغ تخفیف: ۵۰۰ هزارتومان کد تخفیف: PAY5SCM", "500000"),
        ("کد تخفیف ۳۰۰ هزارتومانی اسنپ‌پی سفارش بده", "300000"),
        ("قیمت: ۷.۰۰۰.۰۰۰ تومان با کد تخفیف: PAYSKQR سفارش بده", "7000000"),
        ("کفش نایکی قیمت: ۶.۵۰۰.۰۰۰ تومان", "6500000"),
        ("کفش ونس قیمت: ۸.۰۰۰.۰۰۰ تومان", "8000000"),
    ]
    a, df = _priced_df(rows)
    p = a._pricing_stats(df)

    assert bool(df["is_promo"].iloc[0]) and bool(df["is_promo"].iloc[1]), "promo posts should be flagged"
    assert not df["is_promo"].iloc[2], "real product with a discount code must NOT be flagged"
    assert p["count_priced"] == 3, f"expected 3 real prices, got {p['count_priced']}"
    assert p["min"] == 6_500_000, f"promo 300K/500K should be gone, min={p['min']}"


def test_price_outlier_trimmed():
    """A lone extreme price is removed by the IQR fence."""
    rows = [("قیمت: %d تومان" % v, str(v)) for v in
            (1_000_000, 1_100_000, 1_200_000, 1_300_000, 1_250_000, 50_000_000)]
    a, df = _priced_df(rows)
    p = a._pricing_stats(df)

    assert p["count_outliers_removed"] >= 1, "50M outlier should be trimmed"
    assert p["max"] < 50_000_000, f"outlier still present, max={p['max']}"


def run():
    tests = [test_promo_post_excluded_real_kept, test_price_outlier_trimmed]
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
