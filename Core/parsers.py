"""
Shared, dependency-free text parsers for Iranian social commerce content.

These helpers were originally embedded inside the Rubino Selenium scraper. They
are pulled out here so any platform scraper (Rubino, Telegram, ...) can reuse the
exact same price / engagement extraction logic and produce a consistent CSV
schema for the downstream analyzer.

Nothing in this module touches Selenium, the network, or the filesystem, so it is
safe to import and unit-test in isolation.
"""

import re

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
ENGLISH_DIGITS = "0123456789"

_DIGIT_TABLE = str.maketrans(
    PERSIAN_DIGITS + ARABIC_DIGITS, ENGLISH_DIGITS * 2
)

# A number token that may contain Persian/Arabic digits plus the various
# thousands separators Iranian sellers use (comma, dot, slash, Persian comma).
_NUM_PATTERN = r"([\d\u0660-\u0669\u06f0-\u06f9,\./،]+)"


def convert_persian_nums(text: str) -> str:
    """Normalize Persian (۰۱۲…) and Arabic (٠١٢…) digits to ASCII."""
    return (text or "").translate(_DIGIT_TABLE)


def safe_int(value):
    """
    Best-effort int conversion. Strips any non-digit characters and returns
    None if nothing numeric remains, so callers never hit `int('')` crashes.
    """
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    try:
        return int(digits)
    except (ValueError, TypeError):
        return None


def parse_engagement_text(text_content: str) -> dict:
    """
    Extract a Toman price plus like/comment counts from free-form Persian caption
    text. Mirrors the battle-tested Rubino logic:

      * Strategy A: a price keyword (قیمت/مبلغ/بها/سرویس) followed by a number.
      * Strategy B: a number immediately followed by a currency word.
      * Applies میلیارد/میلیون/هزار (and m/k) multipliers from the trailing context.

    Returns {"price": <str or "None">, "likes": int, "comments": int}.
    Note: on platforms that expose reactions/views instead of likes (e.g. the
    Telegram web preview), the caller supplies engagement separately and only the
    ``price`` field of this result is typically used.
    """
    text = (text_content or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")

    match_a = re.search(
        r"(?:قیمت|مبلغ|بها|سرویس)[^\d\u0660-\u0669\u06f0-\u06f9]{0,25}?" + _NUM_PATTERN,
        text,
    )
    match_b = re.search(
        _NUM_PATTERN + r"\s*(?:تومان|تومانی|هزار|میلیون|ریال|T|t)",
        text,
    )
    best_match = match_a if match_a else match_b

    price = "None"
    if best_match:
        raw_price = best_match.group(1)
        clean = re.sub(r"[,/\.،]", "", raw_price)
        price_int = safe_int(convert_persian_nums(clean))

        if price_int is not None:
            end_idx = best_match.end(1)
            context = text[end_idx : end_idx + 25].lower()

            if "میلیارد" in context:
                price_int *= 1_000_000_000
            elif "میلیون" in context or "m" in context:
                price_int *= 1_000_000
            elif "هزار" in context or "k" in context:
                price_int *= 1_000

            price = str(price_int)

    likes_match = re.search(_NUM_PATTERN + r"\s*(?:لایک|مشاهده)", text)
    likes = (safe_int(convert_persian_nums(re.sub(r"[,/\.،]", "", likes_match.group(1)))) or 0) if likes_match else 0

    comments_match = re.search(_NUM_PATTERN + r"\s*کامنت", text)
    comments = (safe_int(convert_persian_nums(re.sub(r"[,/\.،]", "", comments_match.group(1)))) or 0) if comments_match else 0

    return {"price": price, "likes": likes, "comments": comments}


def parse_price(text_content: str) -> str:
    """Convenience wrapper returning only the parsed price string ('None' if absent)."""
    return parse_engagement_text(text_content)["price"]


def parse_human_count(text: str):
    """
    Parse Telegram-style abbreviated counts into integers.

    Handles ASCII/Persian digits, decimals, and K/M/G/B suffixes:
        "2.58M" -> 2580000, "12.3K" -> 12300, "۱٬۲۰۰" -> 1200, "845" -> 845.
    Returns None when no number is present.
    """
    if not text:
        return None
    t = convert_persian_nums(str(text)).strip().replace(",", "").replace("\u066c", "").replace("،", "")
    m = re.search(r"([\d]+(?:\.[\d]+)?)\s*([KkMmGgBb]?)", t)
    if not m:
        return None
    value = float(m.group(1))
    suffix = m.group(2).lower()
    multiplier = {"k": 1_000, "m": 1_000_000, "g": 1_000_000_000, "b": 1_000_000_000}.get(suffix, 1)
    return int(round(value * multiplier))
