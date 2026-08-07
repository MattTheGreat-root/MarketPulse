"""
Product categorization engine.

The old approach was a first-match-wins substring scan over a flat keyword
dict. On real Persian shop data it failed three ways at once:

  1. Substring collisions   - "کیف" (bag) matched inside "کیفیت" (quality),
                              "کت" (coat) matched inside "کتونی" (sneaker).
  2. Order dependence        - Bag/Coat were defined before Shoes, so they
                              stole every match; a shoe shop produced zero
                              "Shoes".
  3. No brand awareness      - Posts carry the real signal in brand/model
                              names ("AJ1", "Air Max 90", "ایرجردن", "ونس")
                              and no category word at all.

This module fixes all three:

  * Persian text is normalized (unify ي/ك, drop diacritics, split on ZWNJ).
  * Matching is token- and phrase-aware with Persian suffix stripping, so
    "کتونی" no longer counts as "کت".
  * Every category is *scored*; the highest weight wins (specific sub-types
    outweigh generic labels), instead of first-match-wins.
  * A brand/model dictionary maps "air max"/"ایرجردن"/"vans" -> Sneakers.
  * An optional Groq LLM pass resolves whatever the offline layer leaves as
    "Other" (brand-only or oddly phrased posts), batched + cached so it costs
    a couple of calls per analysis. Falls back cleanly with no API key.

Category labels are bilingual, "English (فارسی)", matching the format the
report layer already expects (report_generator._cat_en strips the English
part for chart rendering).
"""

import re
import json


# ---------------------------------------------------------------------------
# Taxonomy: canonical bilingual label -> matching config.
#   kw     : specific keywords (weight 2) - a strong signal for this sub-type.
#   generic: broad keywords (weight 1)    - correct domain, less specific.
# Keywords may be single Persian/English tokens or multi-word phrases.
# Sub-types are ordered specific -> generic within each domain; ties break
# toward whichever scored higher, and equal scores prefer the earlier entry.
# ---------------------------------------------------------------------------
TAXONOMY = {
    # ---- Shoes ------------------------------------------------------------
    "Sneakers (کتونی)":        {"kw": ["کتونی", "کتانی", "کفش ورزشی", "اسنیکر", "ونس",
                                        "sneaker"], "generic": []},
    "Boots (بوت)":             {"kw": ["بوت", "نیم‌بوت", "نیم بوت", "نیمبوت", "چکمه",
                                        "boot", "نیم‌چکمه"], "generic": []},
    "Heels (کفش پاشنه‌دار)":    {"kw": ["پاشنه بلند", "پاشنه‌دار", "پاشنه‌بلند", "هیل",
                                        "heel", "کفش مجلسی"], "generic": []},
    "Sandals (صندل)":          {"kw": ["صندل", "دمپایی", "sandal", "اسلاید", "slide",
                                        "کفش تابستانی"], "generic": []},
    "Loafers (کالج)":          {"kw": ["کالج", "لوفر", "loafer", "کفش کالج"], "generic": []},
    "Formal Shoes (کفش کلاسیک)": {"kw": ["کفش کلاسیک", "کفش رسمی", "کفش چرم",
                                         "کفش اداری"], "generic": []},
    "Shoes (کفش)":             {"kw": [], "generic": ["کفش", "footwear", "shoe"]},

    # ---- Tops / Clothing --------------------------------------------------
    "T-Shirt/Polo (تیشرت)":    {"kw": ["تیشرت", "تی‌شرت", "تی شرت", "پولوشرت", "پولو",
                                        "t-shirt", "tshirt", "tee", "polo"], "generic": []},
    "Hoodie/Sweatshirt (هودی)": {"kw": ["هودی", "سویشرت", "سوییشرت", "hoodie",
                                         "sweatshirt", "کراپ"], "generic": []},
    # "بافت" is demoted to generic (weight 1): it means both "knit sweater" and
    # "texture/weave", so "کیف با بافت چرم" (leather-textured bag) must not beat
    # the actual product. پلیور/ژاکت/پولیور stay strong so real sweaters win.
    "Sweater (بافت)":          {"kw": ["پلیور", "ژاکت", "sweater", "پولیور"],
                                "generic": ["بافت"]},
    "Shirt (پیراهن)":          {"kw": ["پیراهن مردانه", "شومیز", "پیراهن یقه", "shirt",
                                        "پیراهن آستین"], "generic": ["پیراهن"]},
    "Dress (لباس مجلسی)":      {"kw": ["لباس مجلسی", "ماکسی", "لباس شب", "لباس زنانه",
                                        "dress", "پیراهن زنانه", "تونیک"], "generic": []},
    # Manteau - one of the most common Iranian women's-clothing items; its
    # absence let stray color words ("رنگ کرم") win. "مانتو مجلسی" resolves here
    # (not Dress, which needs the phrase "لباس مجلسی", not bare "مجلسی").
    "Manteau (مانتو)":         {"kw": ["مانتو", "مانتوی", "مانتو شومیز", "مانتو مجلسی",
                                        "مانتو اداری", "مانتومزون", "manteau"],
                                "generic": []},
    "Pants (شلوار)":           {"kw": ["شلوار", "جین", "جینز", "شلوار پارچه", "دمپا",
                                        "pants", "jean", "trouser", "کارگو"], "generic": []},
    "Shorts (شلوارک)":         {"kw": ["شلوارک", "شورت", "short"], "generic": []},
    "Skirt (دامن)":            {"kw": ["دامن", "skirt", "مینی‌ژوپ"], "generic": []},
    "Jacket/Coat (کاپشن/پالتو)": {"kw": ["کاپشن", "پالتو", "بارانی", "بمبر", "بومبر",
                                         "اورکت", "پافر", "jacket", "coat", "پانچو"],
                                  "generic": ["کت"]},
    "Suit (کت و شلوار)":       {"kw": ["کت و شلوار", "کت‌وشلوار", "کت شلوار", "suit",
                                        "ست رسمی"], "generic": []},
    "Activewear (ورزشی)":      {"kw": ["ست ورزشی", "لگ", "لگینگ", "گرمکن", "activewear",
                                        "legging", "تاپ ورزشی"], "generic": []},

    # ---- Bags -------------------------------------------------------------
    "Backpack (کوله)":         {"kw": ["کوله", "کوله‌پشتی", "کوله پشتی", "backpack"],
                                "generic": []},
    "Handbag (کیف دستی)":      {"kw": ["کیف دستی", "کیف دوشی", "کیف زنانه", "handbag",
                                        "کیف مجلسی", "clutch", "کلاچ"], "generic": []},
    "Wallet (کیف پول)":        {"kw": ["کیف پول", "جاکارتی", "wallet", "کیف کارت"],
                                "generic": []},
    "Bag (کیف)":               {"kw": [], "generic": ["کیف", "bag", "ساک"]},

    # ---- Accessories ------------------------------------------------------
    "Hat (کلاه)":              {"kw": ["کلاه", "کپ", "beanie", "cap", "hat",
                                        "نقاب دار"], "generic": []},
    "Belt (کمربند)":           {"kw": ["کمربند", "belt"], "generic": []},
    "Scarf/Shawl (شال/روسری)": {"kw": ["شال", "روسری", "اسکارف", "scarf", "shawl",
                                        "مقنعه"], "generic": []},
    "Sunglasses (عینک)":       {"kw": ["عینک آفتابی", "عینک طبی", "عینک", "sunglass",
                                        "glasses"], "generic": []},
    "Socks (جوراب)":           {"kw": ["جوراب", "sock"], "generic": []},
    "Gloves (دستکش)":          {"kw": ["دستکش", "glove"], "generic": []},
    "Tie (کراوات)":            {"kw": ["کراوات", "پاپیون", "tie", "bow tie"], "generic": []},

    # ---- Jewelry ----------------------------------------------------------
    "Bangle (النگو)":          {"kw": ["النگو", "النگوی", "bangle"], "generic": []},
    "Ring (انگشتر)":           {"kw": ["انگشتر", "حلقه", "ring"], "generic": []},
    "Necklace (گردنبند)":      {"kw": ["گردنبند", "گردن‌بند", "پلاک گردنبند",
                                        "necklace", "pendant"], "generic": []},
    "Bracelet (دستبند)":       {"kw": ["دستبند", "bracelet"], "generic": []},
    "Earrings (گوشواره)":      {"kw": ["گوشواره", "earring"], "generic": []},
    "Anklet (پابند)":          {"kw": ["پابند", "anklet", "خلخال"], "generic": []},
    "Jewelry Set (سرویس)":     {"kw": ["سرویس طلا", "نیم‌ست", "نیم ست", "نیمست",
                                        "سرویس", "half set", "ست جواهر"], "generic": []},

    # ---- Watches ----------------------------------------------------------
    # Bare "ساعت" is intentionally excluded - it usually means "o'clock"
    # (opening hours, "از ساعت ۱۱"). Watch products use a compound form or a
    # brand, both covered here.
    "Watch (ساعت)":            {"kw": ["ساعت مچی", "ساعت هوشمند", "ساعت دیجیتال",
                                        "اسمارت واچ", "watch", "smartwatch",
                                        "wristwatch"], "generic": []},

    # ---- Fragrance & Beauty ----------------------------------------------
    "Perfume (عطر/ادکلن)":     {"kw": ["عطر", "ادکلن", "ادوپرفیوم", "ادوتویلت", "بادی اسپلش",
                                        "perfume", "fragrance", "اسپری بدن"], "generic": []},
    "Makeup (لوازم آرایش)":    {"kw": ["رژلب", "رژ لب", "ریمل", "کرم پودر", "فاندیشن",
                                        "سایه چشم", "هایلایتر", "کانسیلر", "خط چشم",
                                        "رژگونه", "پنکک", "lipstick", "mascara",
                                        "makeup", "میکاپ", "آرایش"], "generic": []},
    # NOTE: bare "کرم" is intentionally NOT a keyword here - it is also the
    # color "cream/beige", ubiquitous in clothing/shoe posts ("مانتو رنگ کرم"),
    # and as a generic it made every cream-colored garment register as Skincare.
    # Real skincare is caught by the specific compounds below (کرم شب/روز/
    # آبرسان/دور چشم/ضدآفتاب). Same rule applies to any color word: never add
    # bare "سرمه"(navy)/"صورتی"(pink)/"طلایی" etc. as keywords.
    "Skincare (مراقبت پوست)":  {"kw": ["ضدآفتاب", "سرم", "مرطوب‌کننده", "کرم آبرسان",
                                        "ماسک صورت", "پاک‌کننده", "کرم دور چشم", "تونر",
                                        "skincare", "serum", "کرم شب", "کرم روز"],
                                "generic": ["لوسیون"]},
    "Haircare (مراقبت مو)":    {"kw": ["شامپو", "ماسک مو", "سرم مو", "نرم‌کننده مو",
                                        "shampoo", "روغن مو"], "generic": []},

    # ---- Home & Living ----------------------------------------------------
    "Home Decor (دکوراسیون)":  {"kw": ["دکوراسیون", "قاب عکس", "شمعدان", "لوستر", "شمع",
                                        "گلدان", "تابلو", "فرش", "سجاده", "پرده",
                                        "رومیزی", "کوسن"], "generic": []},

    # ---- Food & Health ----------------------------------------------------
    "Food & Health (سلامت/غذا)": {"kw": ["مکمل", "ویتامین", "پروتئین وی", "کراتین",
                                         "بیوتین", "عسل", "زعفران", "چای", "دمنوش",
                                         "supplement", "protein", "کلاژن"], "generic": []},

    # ---- Electronics ------------------------------------------------------
    "Electronics (لوازم دیجیتال)": {"kw": ["هدفون", "ایرپاد", "هندزفری", "پاوربانک",
                                           "شارژر", "اسپیکر", "airpod", "headphone",
                                           "smartwatch band", "موبایل"], "generic": []},
}

# ---------------------------------------------------------------------------
# Brand / model dictionary: many posts name only a model ("AJ1", "Air Max 90",
# "ایرجردن", "ونس نو اسکول") with no category word. These map straight to a
# canonical label with a strong weight so they win over stray generic hits.
# Keys are matched as normalized phrases/tokens (see _phrase_in / token set).
# ---------------------------------------------------------------------------
BRAND_MAP = {
    "Sneakers (کتونی)": [
        # Latin
        "air jordan", "jordan", "aj1", "aj4", "air max", "airmax", "air force",
        "af1", "dunk", "nike", "adidas", "yeezy", "ultraboost", "nmd", "samba",
        "gazelle", "campus", "new balance", "puma", "reebok", "vans", "converse",
        "asics", "salomon", "sb dunk", "blazer", "cortez", "forum", "superstar",
        # Persian transliterations
        "ایرجردن", "ایر جردن", "جردن", "ایرمکس", "ایر مکس", "ایرفورس", "نایک",
        "نایکی", "آدیداس", "ادیداس", "ییزی", "دانک", "ونس", "کانورس", "سامبا",
        "نیوبالانس", "پوما", "ریبوک", "بلیزر",
    ],
    "Watch (ساعت)": [
        "rolex", "casio", "seiko", "omega", "apple watch", "garmin",
        "رولکس", "کاسیو", "سیکو", "اپل واچ",
    ],
    "Perfume (عطر/ادکلن)": [
        "dior sauvage", "bleu de chanel", "creed", "aventus", "tom ford",
        "دیور", "شنل", "کرید", "تام فورد",
    ],
    "Handbag (کیف دستی)": [
        "louis vuitton", "gucci bag", "hermes", "prada bag", "chanel bag",
    ],
}

# Weights
W_BRAND = 5
W_KW = 2
W_GENERIC = 1
W_HINT = 0.5          # tiny tie-break nudge toward an operator-supplied domain

FALLBACK = "Other"

# ---------------------------------------------------------------------------
# Coarse domain map: fine bilingual label -> shop domain. Used by the adaptive
# drill-down (analyzer) to decide when a shop is essentially ONE domain, and by
# the operator hint to bias/force a domain. Built by inverting a domain->labels
# grouping so it stays a single source of truth; a test asserts every TAXONOMY /
# brand-only label has an entry (guards against drift when the taxonomy grows).
# ---------------------------------------------------------------------------
_DOMAIN_GROUPS = {
    "Shoes": ["Sneakers (کتونی)", "Boots (بوت)", "Heels (کفش پاشنه‌دار)",
              "Sandals (صندل)", "Loafers (کالج)", "Formal Shoes (کفش کلاسیک)",
              "Shoes (کفش)"],
    "Clothing": ["T-Shirt/Polo (تیشرت)", "Hoodie/Sweatshirt (هودی)",
                 "Sweater (بافت)", "Shirt (پیراهن)", "Dress (لباس مجلسی)",
                 "Manteau (مانتو)", "Pants (شلوار)", "Shorts (شلوارک)",
                 "Skirt (دامن)", "Jacket/Coat (کاپشن/پالتو)", "Suit (کت و شلوار)",
                 "Activewear (ورزشی)"],
    "Bags": ["Backpack (کوله)", "Handbag (کیف دستی)", "Wallet (کیف پول)",
             "Bag (کیف)"],
    "Accessories": ["Hat (کلاه)", "Belt (کمربند)", "Scarf/Shawl (شال/روسری)",
                    "Sunglasses (عینک)", "Socks (جوراب)", "Gloves (دستکش)",
                    "Tie (کراوات)"],
    "Jewelry": ["Bangle (النگو)", "Ring (انگشتر)", "Necklace (گردنبند)",
                "Bracelet (دستبند)", "Earrings (گوشواره)", "Anklet (پابند)",
                "Jewelry Set (سرویس)"],
    "Watches": ["Watch (ساعت)"],
    "Fragrance": ["Perfume (عطر/ادکلن)"],
    "Beauty": ["Makeup (لوازم آرایش)", "Skincare (مراقبت پوست)",
               "Haircare (مراقبت مو)"],
    "Home": ["Home Decor (دکوراسیون)"],
    "Health": ["Food & Health (سلامت/غذا)"],
    "Electronics": ["Electronics (لوازم دیجیتال)"],
}
DOMAIN_MAP = {label: domain
              for domain, labels in _DOMAIN_GROUPS.items()
              for label in labels}

# Free-text operator hint -> canonical domain. Accepts English + Persian.
_HINT_SYNONYMS = {
    "Shoes": ["shoe", "shoes", "sneaker", "sneakers", "کفش", "کتونی", "کتانی"],
    "Clothing": ["clothing", "clothes", "apparel", "لباس", "پوشاک", "مانتو",
                 "مزون"],
    "Bags": ["bag", "bags", "کیف", "کوله"],
    "Accessories": ["accessory", "accessories", "اکسسوری", "زیورآلات جانبی"],
    "Jewelry": ["jewelry", "jewellery", "طلا", "جواهر", "زیورآلات", "بدلیجات"],
    "Watches": ["watch", "watches", "ساعت"],
    "Fragrance": ["perfume", "fragrance", "عطر", "ادکلن"],
    "Beauty": ["beauty", "cosmetics", "makeup", "skincare", "آرایش",
               "آرایشی", "بهداشتی", "مراقبت پوست"],
    "Home": ["home", "decor", "دکور", "دکوراسیون"],
    "Health": ["health", "supplement", "سلامت", "مکمل"],
    "Electronics": ["electronics", "digital", "دیجیتال", "لوازم دیجیتال"],
}


def domain_of(label: str) -> str:
    """Coarse domain for a fine category label ('Sneakers (کتونی)' -> 'Shoes')."""
    return DOMAIN_MAP.get(label, "Other")


def resolve_domain_hint(raw) -> str | None:
    """Map a free-text operator hint to a canonical domain, or None if blank /
    unrecognized (which keeps behavior fully automatic)."""
    if not raw:
        return None
    norm = normalize(str(raw))
    if not norm:
        return None
    for domain, words in _HINT_SYNONYMS.items():
        for w in words:
            wn = normalize(w)
            if wn and (wn == norm or wn in norm.split() or _phrase_in(wn, norm)):
                return domain
    return None


# ---------------------------------------------------------------------------
# Attribute detectors for the adaptive drill-down. Each returns a single label
# (the value with the most keyword hits) or None. Pure/offline, same matching
# engine as the taxonomy so Persian suffixes/phrases work identically.
# ---------------------------------------------------------------------------
BRAND_ALIASES = {
    "Nike": ["nike", "نایک", "نایکی", "air max", "airmax", "ایرمکس", "ایر مکس",
             "air force", "af1", "ایرفورس", "air jordan", "jordan", "aj1", "aj4",
             "ایرجردن", "ایر جردن", "جردن", "dunk", "دانک", "sb dunk", "blazer",
             "بلیزر", "cortez", "nocta"],
    "Adidas": ["adidas", "آدیداس", "ادیداس", "yeezy", "ییزی", "ultraboost", "nmd",
               "samba", "سامبا", "gazelle", "campus", "forum", "superstar"],
    "New Balance": ["new balance", "نیوبالانس"],
    "Puma": ["puma", "پوما"],
    "Reebok": ["reebok", "ریبوک"],
    "Vans": ["vans", "ونس"],
    "Converse": ["converse", "کانورس", "all star", "آل استار"],
    "Asics": ["asics", "asic"],
    "Salomon": ["salomon", "سالومون"],
    # watches
    "Rolex": ["rolex", "رولکس"],
    "Casio": ["casio", "کاسیو"],
    "Seiko": ["seiko", "سیکو"],
    "Omega": ["omega", "امگا"],
    "Apple": ["apple watch", "اپل واچ"],
    "Garmin": ["garmin", "گارمین"],
    # perfume houses
    "Dior": ["dior", "دیور", "sauvage", "ساواج"],
    "Chanel": ["chanel", "شنل"],
    "Creed": ["creed", "کرید", "aventus"],
    "Tom Ford": ["tom ford", "تام فورد"],
    # luxury bags
    "Louis Vuitton": ["louis vuitton", "لویی ویتون"],
    "Gucci": ["gucci", "گوچی"],
    "Hermes": ["hermes", "هرمس"],
    "Prada": ["prada", "پرادا"],
}

_GENDER_ALIASES = {
    "مردانه": ["مردانه", "مردونه", "men", "mens", "آقایان"],
    "زنانه": ["زنانه", "زنونه", "women", "womens", "بانوان", "لیدیز"],
    "بچگانه": ["بچگانه", "بچه گانه", "kids", "kid", "پسرانه", "دخترانه", "نوزادی"],
    "یونیسکس": ["یونیسکس", "unisex"],
}

_MATERIAL_ALIASES = {
    "چرم": ["چرم", "چرمی", "leather"],
    "جیر": ["جیر", "suede"],
    "نخی": ["نخی", "پنبه", "cotton"],
    "جین": ["جین", "جینز", "denim"],
    "کتان": ["کتان", "linen"],
    "استیل": ["استیل", "steel", "stainless"],
    "طلا": ["طلا", "gold"],
    "نقره": ["نقره", "silver"],
}

# Persian noun suffixes that may attach to a keyword token (plural / definite /
# possessive). A token matches a keyword if stripping one of these suffixes
# yields the keyword exactly - so "کفش‌ها"/"کفشها" match "کفش" but "کتونی"
# never reduces to "کت".
_PERSIAN_SUFFIXES = ["هایی", "های", "ها", "یی", "ات", "ان", "ی", "ه", "شان",
                     "تان", "مان", "ش", "ت", "م"]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
_DIACRITICS = re.compile(r"[ً-ْٰ]")           # harakat / tanwin
_ARABIC_TO_PERSIAN = str.maketrans({
    "ي": "ی", "ك": "ک", "ﻻ": "لا", "ة": "ه", "أ": "ا", "إ": "ا", "آ": "ا",
    "ؤ": "و", "ئ": "ی", "ٱ": "ا",
})
# Persian/Arabic-Indic digits -> ASCII (so "۹۰" == "90")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.translate(_ARABIC_TO_PERSIAN).translate(_DIGITS)
    text = _DIACRITICS.sub("", text)
    text = text.replace("‌", " ").replace("‏", " ").replace("‎", " ")
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# Payment / promo jargon that collides with product keywords and must be
# stripped before scoring. Iranian shops widely advertise installment payment
# (Snapp Pay / اسنپ‌پی) and cashback into a digital "wallet" (کیف پول), which
# would otherwise register as a Bag/Wallet product. These are phrases, matched
# after normalization. A real wallet product ("کیف پول چرم") still scores via
# its own material/brand words; the bare cashback phrase does not.
_NOISE_PHRASES = [
    "کیف پولتون", "کیف پولت", "کیف پولتان", "کیف پول شما", "کیف پول دیجیتال",
    "به کیف پول", "کیف پول اسنپ",
]


def _strip_noise(norm_text: str) -> str:
    for phrase in _NOISE_PHRASES:
        norm_text = norm_text.replace(phrase, " ")
    return norm_text


# Token = run of Persian or Latin letters/digits. Used for whole-word matching.
_TOKEN_RE = re.compile(r"[a-z0-9]+|[؀-ۿ]+")


def _tokens(norm_text: str) -> set:
    return set(_TOKEN_RE.findall(norm_text))


def _token_matches(token: str, keyword: str) -> bool:
    """Whole-word match with Persian suffix tolerance and English plural 's'."""
    if token == keyword:
        return True
    if token.startswith(keyword):
        rest = token[len(keyword):]
        if rest == "s":                       # English plural
            return True
        if rest in _PERSIAN_SUFFIXES:         # Persian plural/definite/possessive
            return True
    return False


def _kw_hit(keyword: str, norm_text: str, token_set: set) -> bool:
    """A keyword hits if it appears as a whole word (single token) or, for
    multi-word keywords, as a bounded phrase in the normalized text."""
    if " " in keyword:
        return _phrase_in(keyword, norm_text)
    return any(_token_matches(t, keyword) for t in token_set)


def _phrase_in(phrase: str, norm_text: str) -> bool:
    # Boundary-aware phrase match; \b works because text/phrase are normalized
    # to letters, digits and single spaces.
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", norm_text) is not None


# ---------------------------------------------------------------------------
# Attribute detection (drill-down axes). Score each candidate value by number
# of alias hits; return the strongest, or None.
# ---------------------------------------------------------------------------
def _detect(text: str, alias_map: dict):
    norm = normalize(text)
    if not norm:
        return None
    tokens = _tokens(norm)
    best, best_hits = None, 0
    for value, aliases in alias_map.items():
        hits = sum(1 for a in aliases if _kw_hit(normalize(a), norm, tokens))
        if hits > best_hits:
            best, best_hits = value, hits
    return best


def detect_brand(text: str):
    """Best-matching brand name in the text, or None. Covers footwear, watches,
    fragrance houses and luxury bags (see BRAND_ALIASES)."""
    return _detect(text, BRAND_ALIASES)


def detect_gender(text: str):
    """Persian gender label (مردانه/زنانه/بچگانه/یونیسکس) or None."""
    return _detect(text, _GENDER_ALIASES)


def detect_material(text: str):
    """Persian material label (چرم/نخی/استیل/طلا…) or None."""
    return _detect(text, _MATERIAL_ALIASES)


# ---------------------------------------------------------------------------
# Pre-normalized keyword tables. The taxonomy/brand strings are authored with
# natural spelling (آ, ي, ك, ZWNJ), but post text is normalized before matching
# (آ→ا, unify ي/ك, drop ZWNJ). Keywords must go through the SAME normalization
# or multi-form words like «ضدآفتاب» silently never match. Compute once at load.
# ---------------------------------------------------------------------------
_NORM_TAXONOMY = {
    label: {
        "kw": [normalize(k) for k in cfg["kw"]],
        "generic": [normalize(k) for k in cfg["generic"]],
    }
    for label, cfg in TAXONOMY.items()
}
_NORM_BRAND_MAP = {
    label: [normalize(b) for b in brands] for label, brands in BRAND_MAP.items()
}


# ---------------------------------------------------------------------------
# Offline scoring classifier
# ---------------------------------------------------------------------------
def classify_offline(text: str, domain_hint: str | None = None) -> str:
    """Score every category over the text and return the best bilingual label,
    or FALLBACK when nothing matches. Pure, deterministic, no network.

    `domain_hint` (a canonical domain from resolve_domain_hint) applies only a
    tiny tie-break nudge (W_HINT) to labels already matched in that domain — it
    never invents a match where the text has none, so a mislabeled hint can't
    force a wrong category onto an unrelated post."""
    norm = normalize(text)
    if not norm:
        return FALLBACK
    norm = _strip_noise(norm)
    tokens = _tokens(norm)

    scores = {}

    # Brand / model signals (strong). Keywords are pre-normalized to match norm.
    for label, brands in _NORM_BRAND_MAP.items():
        hits = sum(1 for b in brands if _kw_hit(b, norm, tokens))
        if hits:
            scores[label] = scores.get(label, 0) + W_BRAND + (hits - 1)

    # Taxonomy keywords (pre-normalized).
    for label, cfg in _NORM_TAXONOMY.items():
        s = 0
        for kw in cfg["kw"]:
            if _kw_hit(kw, norm, tokens):
                s += W_KW
        for kw in cfg["generic"]:
            if _kw_hit(kw, norm, tokens):
                s += W_GENERIC
        if s:
            scores[label] = scores.get(label, 0) + s

    if not scores:
        return FALLBACK

    # Optional operator hint: a tiny nudge (W_HINT) toward labels already matched
    # in the hinted domain. Only touches labels that actually scored, so it can
    # break a tie in the shop's favor but never invents a category from nothing.
    if domain_hint:
        for label in list(scores):
            if domain_of(label) == domain_hint:
                scores[label] += W_HINT

    # Highest score wins; ties break toward the earlier (more specific) entry.
    order = {label: i for i, label in enumerate(_all_labels())}
    best = max(scores.items(), key=lambda kv: (kv[1], -order.get(kv[0], 999)))
    return best[0]


def _all_labels():
    # BRAND_MAP labels first-seen order then taxonomy order; taxonomy is the
    # canonical specificity order, so build from it and append brand-only ones.
    labels = list(TAXONOMY.keys())
    for label in BRAND_MAP:
        if label not in labels:
            labels.append(label)
    return labels


# English label -> full bilingual label, for mapping LLM output back.
def _english_to_label():
    out = {}
    for label in _all_labels():
        eng = label.split("(", 1)[0].strip().lower()
        out[eng] = label
        # also index each slash-separated alias, e.g. "jacket/coat"
        for part in re.split(r"[/,]", eng):
            part = part.strip()
            if part:
                out.setdefault(part, label)
    return out


# ---------------------------------------------------------------------------
# Public classifier: offline first, optional LLM to rescue "Other".
# ---------------------------------------------------------------------------
class ProductClassifier:
    """
    Classify a batch of product descriptions.

      offline pass  - scoring keyword + brand matcher (always runs).
      llm pass      - for descriptions the offline pass left as "Other", ask
                      Groq to pick from the fixed label list. Batched over the
                      unique texts and cached, so cost is a couple of calls.
    """

    def __init__(self, groq_client=None, use_llm=True, llm_model="llama-3.3-70b-versatile"):
        self.groq_client = groq_client
        self.use_llm = use_llm and groq_client is not None
        self.llm_model = llm_model
        self._cache = {}

    # -- batch entry point --------------------------------------------------
    def classify_many(self, texts, domain_hint: str | None = None) -> list:
        """Classify a batch of product descriptions.

        `domain_hint`: optional canonical domain (Shoes/Clothing/...) to nudge
        ambiguous results toward the shop's known type. Applied per-text via
        classify_offline. Forwarded from analyzer when the operator gives one."""
        texts = ["" if t is None else str(t) for t in texts]
        results = [classify_offline(t, domain_hint=domain_hint) for t in texts]

        if not self.use_llm:
            return results

        # Collect unique, meaningful descriptions the offline pass missed.
        need = {}
        for i, (t, r) in enumerate(zip(texts, results)):
            if r != FALLBACK:
                continue
            key = normalize(t)
            if len(key) < 8:                 # too short to classify meaningfully
                continue
            if key in self._cache:
                results[i] = self._cache[key]
                continue
            need.setdefault(key, (i, t))

        if not need:
            return results

        llm_labels = self._llm_classify([v[1] for v in need.values()])
        for (key, (idx, _)), label in zip(need.items(), llm_labels):
            self._cache[key] = label
            results[idx] = label
        # Apply cache to any duplicates that shared a key.
        for i, (t, r) in enumerate(zip(texts, results)):
            if r == FALLBACK:
                key = normalize(t)
                if key in self._cache:
                    results[i] = self._cache[key]
        return results

    # -- LLM pass -----------------------------------------------------------
    def _llm_classify(self, texts, chunk=40) -> list:
        labels_out = []
        eng_map = _english_to_label()
        allowed = sorted({label.split("(", 1)[0].strip() for label in _all_labels()})
        for start in range(0, len(texts), chunk):
            batch = texts[start:start + chunk]
            labels_out.extend(self._llm_call(batch, allowed, eng_map))
        return labels_out

    def _llm_call(self, batch, allowed, eng_map) -> list:
        items = [{"i": i, "text": (t or "")[:350]} for i, t in enumerate(batch)]
        sys_prompt = (
            "You are an e-commerce product classifier. Each item is a social "
            "media post (often Persian/Farsi, sometimes with English brand or "
            "model names) selling ONE product. Identify the product category.\n\n"
            "Choose EXACTLY ONE category per item from this list "
            "(return the English name only):\n"
            + ", ".join(allowed) + ", Other\n\n"
            "Rules:\n"
            "- Use brand/model names as strong hints (e.g. Air Jordan, Air Max, "
            "Vans, Nike, Adidas, ایرجردن, ایرمکس, ونس => Sneakers).\n"
            "- If the post is an announcement/discount with no specific product, "
            "return \"Other\".\n"
            "- Respond ONLY with JSON: {\"results\":[{\"i\":0,\"category\":\"...\"}, ...]} "
            "with one entry per input item. No markdown, no prose."
        )
        user = json.dumps({"items": items}, ensure_ascii=False)
        try:
            resp = self.groq_client.chat.completions.create(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            got = {int(r["i"]): str(r.get("category", "")).strip()
                   for r in data.get("results", []) if "i" in r}
        except Exception as e:
            print(f"[!] LLM categorization failed, keeping offline results: {e}")
            return [FALLBACK] * len(batch)

        out = []
        for i in range(len(batch)):
            eng = got.get(i, "").lower()
            out.append(eng_map.get(eng, FALLBACK))
        return out
