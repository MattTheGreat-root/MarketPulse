"""
Offline classifier regression tests.

Covers:
  * the real failure that started this: OXO sneaker posts must be Shoes/Sneakers,
    never Bag/Coat/Necklace.
  * cross-domain coverage (jewelry, watch, perfume, bag, clothing, cosmetics)
    so the engine works for any shop type, not just shoes.
  * the homonym traps we hit: کیفیت(quality), کتونی(sneaker vs کت), پلاک(addr),
    ساعت(o'clock), ساق(shaft vs sock).

Run: python -m pytest tests/test_classifier.py  (or: python tests/test_classifier.py)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.classifier import (  # noqa: E402
    classify_offline,
    detect_brand,
    detect_gender,
    detect_material,
    domain_of,
    resolve_domain_hint,
    TAXONOMY,
    BRAND_MAP,
    DOMAIN_MAP,
)


def _domain(label):
    """Reduce a bilingual label to its English head for coarse assertions."""
    return label.split("(", 1)[0].strip()


# (description, expected English head) ---------------------------------------
CASES = [
    # --- real OXO sneaker posts (the original bug) ---
    ("ایرجردن ساق کوتاه مشکی با اسووش طوسی\nAJ1 Dark Gum\nSize : 40 - 46", "Sneakers"),
    ("ایرمکس ۹۰ سرمه‌ای مشکی\nAir Max 90 Off Noir\nPrice : 10,000,000 T", "Sneakers"),
    ("ونس نو اسکول طوسی مشکی با زیره‌ی سفید\nVans Knu Skool", "Sneakers"),
    ("Air Force 1 Nocta مشکی", "Sneakers"),
    ("بلیزر نیم ساق سفید با دو اسووش نایکی", "Sneakers"),
    ("کفش راحتی روزمره با متریال چرم مصنوعی با کیفیت", "Shoes"),  # کیفیت must NOT be Bag
    # --- homonym traps ---
    ("فروشگاه حضوری همه روزه از ساعت ۱۱ صبح تا ۹ شب", "Other"),   # ساعت = o'clock
    ("آدرس: خیابان ولیعصر، پلاک ۱۰۱", "Other"),                   # پلاک = building no.
    ("با اسنپ‌پی خرید کن، ۷٪ مبلغ به کیف پولتون برمی‌گرده", "Other"),  # e-wallet cashback, not a Bag
    ("کیف پول چرم طبیعی مردانه جادار", "Wallet"),                 # a real wallet product still classifies
    # --- cross-domain: prove generality ---
    ("النگو طلاروس ۶ عددی، سرویس کامل", "Bangle"),
    ("گردنبند نقره با آبکاری طلا", "Necklace"),
    ("انگشتر نقره مردانه با نگین عقیق", "Ring"),
    ("ساعت مچی مردانه استیل ضدآب", "Watch"),
    ("عطر مردانه دیور ساواج ادوپرفیوم اصل", "Perfume"),
    ("کیف دستی زنانه چرم طبیعی", "Handbag"),
    ("کوله پشتی ضدآب مناسب لپ تاپ", "Backpack"),
    ("تیشرت نخی یقه گرد اورسایز", "T-Shirt/Polo"),
    ("شلوار جین مام فیت آبی", "Pants"),
    ("کاپشن پافر زمستانی ضد آب", "Jacket/Coat"),
    ("رژلب مات بادوام ضدآب", "Makeup"),
    ("کرم ضدآفتاب SPF50 مناسب پوست چرب", "Skincare"),
    ("عینک آفتابی پلاریزه یووی ۴۰۰", "Sunglasses"),
    ("کمربند چرم طبیعی مردانه", "Belt"),
    # --- pure promo => Other ---
    ("کد تخفیف اسنپ‌پی فقط تا امشب! مبلغ تخفیف ۵۰۰ هزار تومان", "Other"),
    # --- phantom-Skincare bug: color «کرم» (cream) must NOT be Skincare ---
    ("مانتو مجلسی رنگ کرم شیک", "Manteau"),          # headline bug
    ("کفش کتونی رنگ کرم", "Sneakers"),               # cream color on a sneaker
    ("شومیز رنگ کرم آستین بلند", "Shirt"),           # cream color on a shirt
    # --- but real skincare compounds still classify after generic removal ---
    ("کرم آبرسان صورت پوست خشک", "Skincare"),
    ("کرم دور چشم ضد چروک", "Skincare"),
    # --- «بافت» homonym: texture/weave must NOT be Sweater ---
    ("کیف دستی زنانه با بافت چرم", "Handbag"),
    ("پلیور بافت مردانه یقه اسکی", "Sweater"),       # real sweater still wins
    # --- blades / knife shop: store-name «چاقو» baseline + specific sub-types ---
    ("فروشگاه چاقوی زنجان\nچاقو بابا ضدزنگ", "Knife"),
    ("چاقوی تاشو ضامن دار گربر تمام استیل", "Folding Knife"),
    ("کارد شکاری استیل دسته چوبی", "Hunting Knife"),
    ("مینی ساطور آشپزخانه تیغه فولادی", "Cleaver"),
    ("قیچی پشم زنی زنجان", "Scissors"),
]


def run():
    failed = 0
    for desc, expected in CASES:
        got = _domain(classify_offline(desc))
        ok = got == expected
        if not ok:
            failed += 1
        mark = "PASS" if ok else "FAIL"
        head = desc.split("\n")[0][:40]
        print(f"[{mark}] expected={expected:14s} got={got:14s} | {head}")
    total = len(CASES)
    print(f"\n{total - failed}/{total} passed")
    return failed


def test_all_cases_pass():
    assert run() == 0


# --- detector units (drill-down axis signals) -------------------------------
def test_detect_brand():
    assert detect_brand("Air Max 90 مشکی") == "Nike"
    assert detect_brand("ونس نو اسکول طوسی") == "Vans"
    assert detect_brand("گردنبند نقره با آبکاری طلا") is None


def test_detect_gender():
    assert detect_gender("مانتو زنانه اداری") == "زنانه"
    assert detect_gender("کفش مردانه چرم") == "مردانه"
    assert detect_gender("تیشرت نخی یقه گرد") is None


def test_detect_material():
    assert detect_material("کیف دستی چرم طبیعی") == "چرم"
    assert detect_material("ساعت مچی استیل ضدآب") == "استیل"
    assert detect_material("گردنبند نقره") == "نقره"


# --- drift guard: every classifiable label maps to a domain ------------------
def test_domain_map_covers_all_labels():
    """Every TAXONOMY label and every brand-only label must have a DOMAIN_MAP
    entry, otherwise the drill-down concentration test silently mislabels it."""
    missing = []
    for label in TAXONOMY:
        if domain_of(label) is None or label not in DOMAIN_MAP:
            missing.append(label)
    for brand_label in BRAND_MAP:
        if domain_of(brand_label) is None or brand_label not in DOMAIN_MAP:
            missing.append(brand_label)
    assert not missing, f"labels missing from DOMAIN_MAP: {missing}"


def test_operator_hint_resolves():
    """Free-text operator hints map to a canonical domain; the knife-shop hint
    that previously no-op'd (falling every post to Other) now resolves to Blades."""
    assert resolve_domain_hint("knife") == "Blades"
    assert resolve_domain_hint("چاقو") == "Blades"
    assert resolve_domain_hint("sneakers") == "Shoes"
    assert resolve_domain_hint("") is None
    assert resolve_domain_hint("قوری") is None      # unrecognized → stays automatic


def _run_extra():
    """Run the non-CASES assertions so the __main__ path exercises them too."""
    extra = [
        test_detect_brand, test_detect_gender, test_detect_material,
        test_domain_map_covers_all_labels, test_operator_hint_resolves,
    ]
    failed = 0
    for fn in extra:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {fn.__name__}: {e}")
    return failed


if __name__ == "__main__":
    rc = run()
    rc += _run_extra()
    sys.exit(1 if rc else 0)
