"""
Telegram channel scraper for MarketPulse.

Design goal: analyze public Telegram shop channels WITHOUT any risk of getting an
account banned. To achieve that this scraper reads the public web preview that
Telegram itself serves at ``https://t.me/s/<channel>``. That endpoint:

  * requires no account, no phone number, and no API keys;
  * is plain server-rendered HTML (no JavaScript / Selenium needed);
  * is the same data any anonymous visitor sees, so there is nothing to ban.

Because it is the *preview*, there are two inherent limitations compared to the
MTProto API:

  * Reactions are usually hidden and comments (discussion-group replies) are NOT
    exposed at all. We therefore leave the ``comments`` column empty. The
    downstream analyzer degrades gracefully: price, engagement, category,
    momentum, pricing and hashtag analysis all still work; only the AI/offline
    *comment* demand-signal section comes back empty.
  * "Engagement" on Telegram is measured by post VIEWS (plus any visible
    reactions), not likes+comments. Views are the strongest public signal of a
    post's reach, so we use them as the engagement metric to stay consistent
    with how the rest of the pipeline ranks "top posts".

If deeper comment-level intelligence is ever required, a second backend based on
MTProto (Telethon/Pyrogram, using a dedicated throwaway account with strict rate
limiting) can be added behind the same ``BaseScraper`` interface without touching
the analyzer or report layers.
"""

import os
import time
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from core.base_scraper import BaseScraper
from core.parsers import parse_engagement_text, parse_human_count


class TelegramScraper(BaseScraper):
    BASE_URL = "https://t.me/s/"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    # Politeness / safety knobs. These keep us well under any anonymous
    # rate-limit and make the scraper a good web citizen.
    PAGE_DELAY_SECONDS = 1.5
    MAX_STAGNANT_PAGES = 3
    REQUEST_TIMEOUT = 30

    def __init__(self, driver, target, output_dir="data"):
        # ``driver`` is accepted only to satisfy the BaseScraper contract; this
        # scraper is pure HTTP and never touches Selenium. main.py passes None.
        super().__init__(driver, target, output_dir)

        # Accept "@channel", "https://t.me/channel", or bare "channel".
        self.target = self._normalize_target(target)

        # Match the Rubino timestamped naming so MarketAnalyzer / ClientPackager
        # (which glob `{username}_*.csv` / `.xlsx`) pick up the freshest run.
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

        # Populated during navigate_to_page() for optional reporting/debugging.
        self.channel_title = None
        self.channel_meta = None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _normalize_target(target: str) -> str:
        """Turn any of @name / t.me/name / https://t.me/s/name into 'name'."""
        t = (target or "").strip()
        t = t.replace("https://", "").replace("http://", "")
        for prefix in ("t.me/s/", "t.me/", "telegram.me/s/", "telegram.me/"):
            if t.startswith(prefix):
                t = t[len(prefix):]
                break
        t = t.lstrip("@").strip("/")
        # A channel handle can't contain a slash/query; keep only the handle part.
        return t.split("/")[0].split("?")[0]

    def _fetch(self, before=None) -> BeautifulSoup:
        url = f"{self.BASE_URL}{self.target}"
        if before:
            url = f"{url}?before={before}"
        resp = self.client.get(url)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")

    def _extract_channel_info(self, soup: BeautifulSoup) -> None:
        title = soup.select_one(".tgme_channel_info_header_title, .tgme_page_title")
        meta = soup.select_one(".tgme_channel_info_counters, .tgme_page_extra")
        if title:
            self.channel_title = title.get_text(" ", strip=True)
        if meta:
            self.channel_meta = meta.get_text(" ", strip=True)

    def _extract_reactions(self, msg_el) -> int:
        """Sum any visible reaction counts on a message (often 0 in preview)."""
        total = 0
        for rel in msg_el.select(".tgme_widget_message_reaction"):
            n = parse_human_count(rel.get_text(" ", strip=True))
            if n:
                total += n
        return total

    def _extract_replies(self, msg_el) -> int:
        """Visible discussion-reply count, if the channel surfaces one."""
        rep = msg_el.select_one(
            ".tgme_widget_message_replies_count, .tgme_widget_message_replies"
        )
        if rep:
            return parse_human_count(rep.get_text(" ", strip=True)) or 0
        return 0

    def _extract_post(self, msg_el, idx: int) -> dict:
        """Map a `.tgme_widget_message` element to the shared CSV schema."""
        text_el = msg_el.select_one(".tgme_widget_message_text")
        description = text_el.get_text("\n", strip=True) if text_el else ""

        views_el = msg_el.select_one(".tgme_widget_message_views")
        views = parse_human_count(views_el.get_text(strip=True)) if views_el else 0
        views = views or 0

        reactions = self._extract_reactions(msg_el)
        replies = self._extract_replies(msg_el)

        # Engagement = reach (views) + any active signals we can see.
        engagement = views + reactions + replies

        # Reuse the shared Persian price parser on the caption text.
        price = parse_engagement_text(description)["price"] if description else "None"

        post_id = msg_el.get("data-post", "")
        post_url = f"https://t.me/{post_id}" if post_id else ""

        date_el = msg_el.select_one(".tgme_widget_message_date time")
        posted_at = date_el.get("datetime", "") if date_el else ""

        # NOTE: column order/names match what MarketAnalyzer consumes. The extra
        # trailing columns (views/reactions/date/url) are ignored by the analyzer
        # but useful in the delivered XLSX.
        return {
            "post_index": idx,
            "description": description,
            "price": price,
            "engagement": engagement,
            "comments": "",  # not available via the public web preview
            "views": views,
            "reactions": reactions,
            "posted_at": posted_at,
            "post_url": post_url,
        }

    # ---------------------------------------------------------- BaseScraper API
    def navigate_to_page(self) -> bool:
        page_url = f"{self.BASE_URL}{self.target}"
        print(f"[*] Checking Telegram channel: {page_url}")
        try:
            soup = self._fetch()
        except httpx.HTTPStatusError as e:
            code = e.response.status_code if e.response is not None else "?"
            print(f"[!] HTTP {code} for channel '{self.target}'. It may not exist.")
            return False
        except Exception as e:
            print(f"[!] Could not reach Telegram for '{self.target}': {e}")
            return False

        msgs = soup.select(".tgme_widget_message")
        if not msgs:
            if soup.select_one(".tgme_page_additional") or "preview" in soup.get_text().lower():
                print(
                    f"[!] Channel '{self.target}' has no public preview "
                    "(it may be private, empty, or restricted to the app)."
                )
            else:
                print(f"[!] No posts found for '{self.target}'. Double-check the username.")
            return False

        self._extract_channel_info(soup)
        title = self.channel_title or self.target
        meta = f" ({self.channel_meta})" if self.channel_meta else ""
        print(f"[+] Found channel: {title}{meta} — {len(msgs)} posts on first page.")
        return True

    def scrape_all_posts(self, max_posts=None) -> list:
        results = []
        seen = set()
        before = None
        stagnant = 0

        print(f"[*] Scraping @{self.target} via public web preview...")
        while True:
            if max_posts and len(results) >= max_posts:
                break

            try:
                soup = self._fetch(before=before)
            except Exception as e:
                print(f"[!] Page fetch failed (before={before}): {e}. Stopping.")
                break

            msgs = soup.select(".tgme_widget_message")
            if not msgs:
                break

            new_in_page = 0
            oldest_id_num = None
            for msg in msgs:
                post_id = msg.get("data-post", "")
                # Track the smallest (oldest) numeric id on the page for paging.
                num = post_id.split("/")[-1] if post_id else ""
                if num.isdigit():
                    n = int(num)
                    if oldest_id_num is None or n < oldest_id_num:
                        oldest_id_num = n

                if post_id and post_id in seen:
                    continue
                if post_id:
                    seen.add(post_id)

                results.append(self._extract_post(msg, len(results) + 1))
                new_in_page += 1
                if max_posts and len(results) >= max_posts:
                    break

            print(f"  -> {len(results)} posts collected...")

            if new_in_page == 0:
                stagnant += 1
                if stagnant >= self.MAX_STAGNANT_PAGES:
                    break
            else:
                stagnant = 0

            # Reached the very beginning of the channel history.
            if oldest_id_num is None or oldest_id_num <= 1:
                break

            before = oldest_id_num
            time.sleep(self.PAGE_DELAY_SECONDS)

        # Web-preview returns newest-first per page and we page backwards, so the
        # list is already in reverse-chronological order. Renumber post_index so
        # it is stable and 1-based in collection order.
        for i, row in enumerate(results, start=1):
            row["post_index"] = i

        print(f"[+] Finished: {len(results)} posts scraped from @{self.target}.")
        if results and all(r["comments"] == "" for r in results):
            print(
                "[i] Note: Telegram's public preview does not expose comments, "
                "so comment-based demand signals will be empty in the report."
            )
        return results

    def run(self, max_posts=None):
        """Lifecycle override: no browser/driver to tear down for HTTP scraping."""
        print(f"[*] Starting Telegram extraction for @{self.target}...")
        try:
            if not self.navigate_to_page():
                print(f"[!] Failed to access channel @{self.target}.")
                return []
            results = self.scrape_all_posts(max_posts=max_posts)
            self.save_to_csv(results)
            return results
        finally:
            self.client.close()
