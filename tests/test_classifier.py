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

from core.classifier import classify_offline  # noqa: E402


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


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
