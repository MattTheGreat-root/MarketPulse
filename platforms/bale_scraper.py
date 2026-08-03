"""
Bale (بله) channel scraper for MarketPulse.

Bale is an Iranian messenger modeled closely on Telegram, and — like Telegram —
it serves a public, server-rendered web *preview* of a channel at

    https://ble.ir/s/<channel>

That endpoint:

  * requires no account, no phone number, and no API keys;
  * returns plain server-rendered HTML (no JavaScript / Selenium needed);
  * is the same data any anonymous visitor sees, so there is nothing to ban.

This mirrors the design of ``TelegramScraper`` on purpose, so the whole pipeline
(analyzer, categorizer, report) consumes an identical CSV schema regardless of
platform.

Differences from Telegram's ``t.me/s/`` preview (documented honestly so nobody
is surprised by the data):

  * NO PAGINATION. Bale's ``/s/`` preview returns only a fixed, recent window
    of the channel (~10 latest posts) and exposes no message ids, cursor, or
    ``before=`` parameter to walk further back. We scrape that window and stop.
    ``max_posts`` can only ever *cap* it lower, never fetch more history. If
    deeper history is ever required it would need Bale's authenticated app API
    (a separate backend behind this same ``BaseScraper`` interface).
  * No comments/replies are exposed, so the ``comments`` column is left empty
    and the analyzer's comment-based demand signals come back empty — exactly
    as with the Telegram preview.
  * "Engagement" is measured by post VIEWS (Bale shows a per-post view count
    like ``۳.۶K``), consistent with how the Telegram backend ranks reach.

The page markup uses CSS-module class names with a hashed suffix
(e.g. ``MessageItem_messageWrapper__E9ZFU``). Those suffixes change between
builds, so every selector here matches on the STABLE class *prefix* rather than
the full name.
"""

import os
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from core.base_scraper import BaseScraper
from core.parsers import parse_engagement_text, parse_human_count


def _has_class_prefix(prefix):
    """BeautifulSoup filter: element has any class starting with ``prefix``.

    Bale's class names are hashed (``Photo_caption__B_CHL``); matching the
    prefix keeps selectors stable across front-end builds."""
    def _match(tag):
        classes = tag.get("class")
        return bool(classes) and any(c.startswith(prefix) for c in classes)
    return _match


class BaleScraper(BaseScraper):
    BASE_URL = "https://ble.ir/s/"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    REQUEST_TIMEOUT = 30

    # Stable class-name prefixes for the fields we extract.
    SEL_MESSAGE = "MessageItem_messageWrapper"
    SEL_CAPTION = ("Photo_caption", "Text_text")   # media caption, else text message
    SEL_VIEWS = "Info_ViewWrapper"
    SEL_CHAT = "ChatWrapper_chat_inner"            # ordered container of the chat
    SEL_DIVIDER = "DateDivider_DateDividerWrapper"  # date separators (carry the date)
    SEL_TIME = "Info_date"                         # per-message HH:MM

    def __init__(self, driver, target, output_dir="data"):
        # ``driver`` is accepted only to satisfy the BaseScraper contract; this
        # scraper is pure HTTP and never touches Selenium. main.py passes None.
        super().__init__(driver, target, output_dir)

        # Accept "@channel", "https://ble.ir/channel", "ble.ir/s/channel", or bare.
        self.target = self._normalize_target(target)

        # Match the Telegram/Rubino timestamped naming so MarketAnalyzer /
        # ClientPackager (which glob `{username}_*.csv` / `.xlsx`) pick up the
        # freshest run.
        safe_target = "".join(c for c in self.target if c.isalnum() or c in ("_", "-"))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_path = os.path.join(self.output_dir, f"{safe_target}_{ts}.csv")

        self.client = httpx.Client(
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fa,en;q=0.8",
            },
            timeout=self.REQUEST_TIMEOUT,
            follow_redirects=True,
        )

        self.channel_title = None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _normalize_target(target: str) -> str:
        """Turn @name / ble.ir/name / https://ble.ir/s/name into 'name'."""
        t = (target or "").strip()
        t = t.replace("https://", "").replace("http://", "")
        for prefix in ("ble.ir/s/", "ble.ir/", "www.ble.ir/s/", "www.ble.ir/"):
            if t.startswith(prefix):
                t = t[len(prefix):]
                break
        t = t.lstrip("@").strip("/")
        # A channel handle can't contain a slash/query; keep only the handle.
        return t.split("/")[0].split("?")[0]

    def _fetch(self) -> BeautifulSoup:
        url = f"{self.BASE_URL}{self.target}"
        resp = self.client.get(url)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")

    def _extract_channel_info(self, soup: BeautifulSoup) -> None:
        og = soup.select_one('meta[property="og:title"]')
        if og and og.get("content"):
            # og:title looks like "بله | کانال OXO STREETWEAR"
            self.channel_title = og["content"].split("|", 1)[-1].strip()
        elif soup.title:
            self.channel_title = soup.title.get_text(strip=True)

    def _caption(self, msg_el) -> str:
        for prefix in self.SEL_CAPTION:
            el = msg_el.find(_has_class_prefix(prefix))
            if el:
                return el.get_text("\n", strip=True)
        return ""

    def _views(self, msg_el) -> int:
        el = msg_el.find(_has_class_prefix(self.SEL_VIEWS))
        if not el:
            return 0
        return parse_human_count(el.get_text(" ", strip=True)) or 0

    @staticmethod
    def _combine_timestamp(divider_iso: str, msg_el) -> str:
        """Bale puts the full date on a preceding DateDivider (ISO ``<time>``)
        and only ``HH:MM`` on each message. Combine them into a single ISO-ish
        timestamp ``YYYY-MM-DDTHH:MM`` so the analyzer can order posts. Falls
        back to the bare divider date (or "") when either part is missing."""
        date_part = (divider_iso or "").split("T", 1)[0]
        if not date_part:
            return ""
        time_el = msg_el.find(_has_class_prefix(BaleScraper.SEL_TIME))
        if not time_el:
            return date_part
        raw = time_el.get_text(strip=True)
        # Normalize Persian digits and pad to HH:MM.
        digits = raw.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        m = re.match(r"(\d{1,2}):(\d{2})", digits)
        if not m:
            return date_part
        return f"{date_part}T{int(m.group(1)):02d}:{m.group(2)}"

    def _extract_post(self, msg_el, idx: int, posted_at: str) -> dict:
        """Map one Bale message element to the shared CSV schema."""
        description = self._caption(msg_el)
        views = self._views(msg_el)

        # Engagement = reach (views). Bale's preview exposes no reactions/replies.
        engagement = views

        price = parse_engagement_text(description)["price"] if description else "None"

        return {
            "post_index": idx,
            "description": description,
            "price": price,
            "engagement": engagement,
            "comments": "",   # not available via the public web preview
            "views": views,
            "reactions": 0,   # not exposed by Bale's preview
            "posted_at": posted_at,
            "post_url": f"https://ble.ir/{self.target}",
        }

    # ---------------------------------------------------------- BaseScraper API
    def navigate_to_page(self) -> bool:
        page_url = f"{self.BASE_URL}{self.target}"
        print(f"[*] Checking Bale channel: {page_url}")
        try:
            soup = self._fetch()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code if e.response is not None else "?"
            print(f"[!] HTTP {code} for channel '{self.target}'. It may not exist.")
            return False
        except Exception as e:
            print(f"[!] Could not reach Bale for '{self.target}': {e}")
            return False

        msgs = soup.find_all(_has_class_prefix(self.SEL_MESSAGE))
        if not msgs:
            print(
                f"[!] No public posts found for '{self.target}'. The channel may "
                "be private, empty, or Bale changed its preview markup."
            )
            return False

        self._extract_channel_info(soup)
        title = self.channel_title or self.target
        print(f"[+] Found channel: {title} — {len(msgs)} posts in public preview.")
        self._soup = soup  # reuse in scrape_all_posts; the preview is one page
        return True

    def scrape_all_posts(self, max_posts=None) -> list:
        print(f"[*] Scraping @{self.target} via Bale public web preview...")
        soup = getattr(self, "_soup", None) or self._fetch()

        # Walk the chat container in document order. Bale interleaves
        # DateDivider elements (which carry the full date) between message
        # groups; each message only knows its HH:MM. Track the running divider
        # date so every post gets a full timestamp. Document order is already
        # oldest -> newest, which matches the analyzer's post_index convention.
        chat = soup.find(_has_class_prefix(self.SEL_CHAT))
        nodes = chat.find_all(recursive=False) if chat else soup.find_all(
            _has_class_prefix(self.SEL_MESSAGE)
        )

        results = []
        current_date_iso = ""
        for node in nodes:
            classes = node.get("class") or []
            if any(c.startswith(self.SEL_DIVIDER) for c in classes):
                time_el = node.find("time")
                if time_el and time_el.get("datetime"):
                    current_date_iso = time_el["datetime"]
                continue
            if not any(c.startswith(self.SEL_MESSAGE) for c in classes):
                continue

            posted_at = self._combine_timestamp(current_date_iso, node)
            post = self._extract_post(node, len(results) + 1, posted_at)
            # Skip fully empty shells (media-only with no caption AND no views).
            if not post["description"] and not post["views"]:
                continue
            results.append(post)

        if max_posts and len(results) > max_posts:
            # Keep the most recent `max_posts` when a cap is given.
            results = results[-max_posts:]

        for i, row in enumerate(results, start=1):
            row["post_index"] = i

        print(f"[+] Finished: {len(results)} posts scraped from @{self.target}.")
        print(
            "[i] Note: Bale's public preview shows only recent posts (no "
            "pagination) and exposes no comments, so history is limited and "
            "comment-based demand signals will be empty in the report."
        )
        return results

    def run(self, max_posts=None):
        """Lifecycle override: no browser/driver to tear down for HTTP scraping."""
        print(f"[*] Starting Bale extraction for @{self.target}...")
        try:
            if not self.navigate_to_page():
                print(f"[!] Failed to access channel @{self.target}.")
                return []
            results = self.scrape_all_posts(max_posts=max_posts)
            self.save_to_csv(results)
            return results
        finally:
            self.client.close()
