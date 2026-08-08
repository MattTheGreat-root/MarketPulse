"""
Bale (بله) channel scraper for MarketPulse.

Bale is an Iranian messenger modeled closely on Telegram, and — like Telegram —
it serves a public, server-rendered web *preview* of a channel at

    https://ble.ir/s/<channel>

That endpoint:

  * requires no account, no phone number, and no API keys;
  * is the same data any anonymous visitor sees, so there is nothing to ban.

This mirrors the design of ``TelegramScraper`` on purpose, so the whole pipeline
(analyzer, categorizer, report) consumes an identical CSV schema regardless of
platform.

How the data actually flows (the important part)
------------------------------------------------
``ble.ir`` is a Next.js app. The ``/s/<channel>`` HTML does *not* contain the
posts as normal markup; instead it ships them as React Server Component
streaming data inside a series of ``self.__next_f.push([1,"…"])`` script calls.
Concatenating and JSON-decoding those payloads yields one blob from which we
pull:

  * ``peer`` — ``{"type":<int>,"id":<int>}`` identifying the channel, and
  * the initial ``messages`` array (the 10 most recent posts).

Deeper history comes from Bale's real load-more backend (this is what the web
client itself calls as you scroll up):

    POST https://api.ble.ir/api/v1/LoadHistory
    body: {"peer": <peer>, "date": <oldest_date_ms_seen_so_far>}

It returns ``{"history": [...]}`` — 10 *older* messages per call. The boundary
message (the one whose date we passed in) is echoed back, so results are
deduplicated by ``rid``. We page backward using the minimum ``date`` of each
batch until the history runs dry or ``max_posts`` is reached. This is the direct
analogue of ``TelegramScraper``'s ``?before=`` paging, so ``max_posts`` now
genuinely controls depth (mini=10, normal=100, pro=all) instead of being capped
at the ~10 posts the first page happens to embed.

Message schema (identical on the initial page and the API):

  * ``rid``        — unique id (used for dedup / stable ordering);
  * ``date``       — epoch **milliseconds** (→ ISO ``posted_at``);
  * ``viewCount``  — per-post reach (→ ``views``);
  * ``reactions``  — list of ``{"code","cardinality"}`` (→ summed ``reactions``);
  * ``message``    — either ``documentMessage`` (media; caption text at
    ``message.documentMessage.caption.text``) or ``textMessage`` (text at
    ``message.textMessage.text``).

Limitations shared with the Telegram preview: no comments/replies are exposed,
so the ``comments`` column is left empty and the analyzer's comment-based demand
signals come back empty. "Engagement" is reach + reactions (views plus summed
reaction cardinalities), consistent with how ``TelegramScraper`` ranks posts.
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from core.base_scraper import BaseScraper
from core.parsers import parse_engagement_text


class BaleScraper(BaseScraper):
    PREVIEW_URL = "https://ble.ir/s/"
    HISTORY_URL = "https://api.ble.ir/api/v1/LoadHistory"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    # Politeness / safety knobs, mirroring TelegramScraper. These keep us well
    # under any anonymous rate-limit and make the scraper a good web citizen.
    PAGE_DELAY_SECONDS = 1.0
    MAX_STAGNANT_PAGES = 3
    # A multi-photo post (media album) is stored by Bale as several separate
    # ``documentMessage`` entries with timestamps a few ms apart; only one
    # sibling carries the caption. Siblings observed ≤5ms apart, while genuinely
    # distinct posts are seconds-to-minutes apart, so this window cleanly
    # separates the two. Album siblings are collapsed into a single logical post
    # (see ``_collapse_albums``) so ``max_posts`` counts real posts and the CSV
    # has no phantom caption-less rows.
    ALBUM_WINDOW_MS = 2000
    # Hard backstop so an unbounded (pro / max_posts=None) run can never loop
    # forever if the API keeps echoing data. ~10 posts/page, so this covers tens
    # of thousands of posts; if it is ever hit we say so rather than truncating
    # silently.
    MAX_PAGES = 2000
    REQUEST_TIMEOUT = 30

    # RSC payloads look like: self.__next_f.push([1,"…escaped json…"])
    _NEXT_PAYLOAD_RE = re.compile(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)')
    # The channel identifier embedded in the streamed blob.
    _PEER_RE = re.compile(r'"peer":\s*(\{"type":\d+,"id":\d+\})')

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
        # Populated by navigate_to_page() so scrape_all_posts() can page onward
        # without re-fetching/re-parsing the initial HTML.
        self._peer = None
        self._initial_messages = None

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

    @staticmethod
    def _extract_balanced_array(text: str, key: str):
        """Return the raw JSON substring for ``"key":[ ... ]`` by balancing
        brackets (string-aware, so brackets inside strings don't confuse it).
        Returns None if the key isn't present."""
        idx = text.find(f'"{key}":[')
        if idx == -1:
            return None
        start = text.index("[", idx)
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
        return None

    def _decode_next_blob(self, html: str) -> str:
        """Concatenate every RSC streaming payload into one decoded string."""
        parts = []
        for raw in self._NEXT_PAYLOAD_RE.findall(html):
            try:
                parts.append(json.loads('"' + raw + '"'))
            except json.JSONDecodeError:
                continue
        return "".join(parts)

    def _parse_initial(self, html: str):
        """From the ``/s/<channel>`` HTML, extract (peer, messages).

        Returns (None, []) if the streamed data can't be located (private/empty
        channel, or Bale changed its serialization)."""
        blob = self._decode_next_blob(html)

        peer = None
        m = self._PEER_RE.search(blob)
        if m:
            try:
                peer = json.loads(m.group(1))
            except json.JSONDecodeError:
                peer = None

        messages = []
        raw = self._extract_balanced_array(blob, "messages")
        if raw:
            try:
                messages = json.loads(raw)
            except json.JSONDecodeError:
                messages = []

        return peer, messages

    def _load_history(self, oldest_date_ms: int) -> list:
        """Fetch the 10 messages immediately older than ``oldest_date_ms``."""
        resp = self.client.post(
            self.HISTORY_URL,
            json={"peer": self._peer, "date": oldest_date_ms},
            headers={
                "Content-Type": "application/json",
                "Origin": "https://ble.ir",
                "Referer": "https://ble.ir/",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("history", []) or []

    @staticmethod
    def _message_text(msg: dict) -> str:
        """Pull the caption/text out of either message shape."""
        inner = msg.get("message") or {}
        doc = inner.get("documentMessage")
        if doc:
            caption = doc.get("caption") or {}
            return caption.get("text", "") or ""
        txt = inner.get("textMessage")
        if txt:
            return txt.get("text", "") or ""
        return ""

    @staticmethod
    def _sum_reactions(msg: dict) -> int:
        """Sum reaction cardinalities: [{'code':'❤','cardinality':5}, ...] -> 5."""
        total = 0
        for r in msg.get("reactions") or []:
            try:
                total += int(r.get("cardinality") or 0)
            except (TypeError, ValueError):
                continue
        return total

    @staticmethod
    def _iso_from_ms(date_ms) -> str:
        """Epoch milliseconds -> ISO 8601 UTC string (or '' if unparseable)."""
        try:
            return datetime.fromtimestamp(int(date_ms) / 1000, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return ""

    def _extract_post(self, msg: dict, idx: int) -> dict:
        """Map one Bale message (dict) to the shared CSV schema."""
        description = self._message_text(msg)
        views = 0
        try:
            views = int(msg.get("viewCount") or 0)
        except (TypeError, ValueError):
            views = 0
        reactions = self._sum_reactions(msg)

        # Engagement = reach (views) + active signal (reactions), matching
        # TelegramScraper's "views + reactions + replies" philosophy. Bale's
        # preview exposes no replies, so replies are simply absent here.
        engagement = views + reactions

        price = parse_engagement_text(description)["price"] if description else "None"

        return {
            "post_index": idx,
            "description": description,
            "price": price,
            "engagement": engagement,
            "comments": "",   # not available via the public web preview
            "views": views,
            "reactions": reactions,
            "posted_at": self._iso_from_ms(msg.get("date")),
            "post_url": f"https://ble.ir/{self.target}",
        }

    @staticmethod
    def _safe_date(msg: dict) -> int:
        try:
            return int(msg.get("date") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _safe_views(msg: dict) -> int:
        try:
            return int(msg.get("viewCount") or 0)
        except (TypeError, ValueError):
            return 0

    def _min_date(self, messages) -> int:
        dates = [self._safe_date(m) for m in messages if self._safe_date(m)]
        return min(dates) if dates else 0

    def _collapse_albums(self, messages) -> list:
        """Merge media-album siblings into one logical post, oldest -> newest.

        Bale posts a photo carousel as N consecutive ``documentMessage`` entries
        a few ms apart, with the caption only on the first one. We walk the
        date-sorted messages and start a new post whenever a message carries its
        own text (a real caption/text post) or falls outside ALBUM_WINDOW_MS of
        the previous one; caption-less media inside the window attach to the
        current album. This means each album yields exactly one row instead of
        one good row plus several caption-less phantoms.
        """
        ordered = sorted(messages, key=self._safe_date)
        groups: list = []
        for m in ordered:
            if not groups:
                groups.append([m])
                continue
            gap = self._safe_date(m) - self._safe_date(groups[-1][-1])
            if self._message_text(m) or gap > self.ALBUM_WINDOW_MS:
                groups.append([m])
            else:
                groups[-1].append(m)
        return [self._merge_group(g) for g in groups]

    def _merge_group(self, group: list) -> dict:
        """Collapse one album's siblings into a single message-shaped dict.

        Uses the captioned sibling for text (albums put it on the oldest one),
        the album's earliest date as the post time, the max per-photo view count
        as reach (summing would multiply a single post's audience), and the
        richest sibling's reaction list (reactions mirror across siblings, so we
        take rather than sum them).
        """
        if len(group) == 1:
            return group[0]
        head = next((m for m in group if self._message_text(m)), group[0])
        merged = dict(head)
        merged["date"] = min(self._safe_date(m) for m in group)
        merged["viewCount"] = max((self._safe_views(m) for m in group), default=0)
        merged["reactions"] = max(group, key=self._sum_reactions).get("reactions") or []
        return merged

    # ---------------------------------------------------------- BaseScraper API
    def navigate_to_page(self) -> bool:
        page_url = f"{self.PREVIEW_URL}{self.target}"
        print(f"[*] Checking Bale channel: {page_url}")
        try:
            resp = self.client.get(page_url)
            resp.raise_for_status()
            html = resp.text
        except httpx.HTTPStatusError as e:
            code = e.response.status_code if e.response is not None else "?"
            print(f"[!] HTTP {code} for channel '{self.target}'. It may not exist.")
            return False
        except Exception as e:
            print(f"[!] Could not reach Bale for '{self.target}': {e}")
            return False

        peer, messages = self._parse_initial(html)
        if not peer or not messages:
            print(
                f"[!] No public posts found for '{self.target}'. The channel may "
                "be private, empty, or Bale changed its preview format."
            )
            return False

        # Channel title from og:title ("بله | کانال …") for nicer logging.
        soup = BeautifulSoup(html, "html.parser")
        og = soup.select_one('meta[property="og:title"]')
        if og and og.get("content"):
            self.channel_title = og["content"].split("|", 1)[-1].strip()

        self._peer = peer
        self._initial_messages = messages
        title = self.channel_title or self.target
        print(f"[+] Found channel: {title} — {len(messages)} posts on first page.")
        return True

    def scrape_all_posts(self, max_posts=None) -> list:
        print(f"[*] Scraping @{self.target} via Bale load-more API...")

        # navigate_to_page() should have primed these; fall back defensively.
        if self._peer is None or self._initial_messages is None:
            if not self.navigate_to_page():
                return []

        # Collect every message keyed by rid (dedup), regardless of the order the
        # API returns them in. We sort by date at the end for a stable
        # oldest->newest post_index.
        collected = {}

        def absorb(messages) -> int:
            added = 0
            for m in messages:
                rid = m.get("rid")
                if rid is None or rid in collected:
                    continue
                collected[rid] = m
                added += 1
            return added

        absorb(self._initial_messages)
        cur_date = self._min_date(self._initial_messages)

        stagnant = 0
        pages = 0
        # We fetch until we have MORE logical posts than requested (or history
        # runs dry). Overshooting by one page guarantees the oldest kept post is
        # a complete album — a partially-fetched album at the frontier is only
        # ever trimmed away, never emitted with missing siblings.
        while not (max_posts and len(self._collapse_albums(collected.values())) > max_posts):
            if pages >= self.MAX_PAGES:
                print(
                    f"[!] Hit MAX_PAGES safety cap ({self.MAX_PAGES}); stopping with "
                    f"{len(collected)} messages. Older history was not fetched."
                )
                break
            if not cur_date:
                break

            try:
                history = self._load_history(cur_date)
            except Exception as e:
                print(f"[!] LoadHistory failed (date={cur_date}): {e}. Stopping.")
                break

            pages += 1
            if not history:
                break  # reached the beginning of the channel

            added = absorb(history)
            print(f"  -> {len(self._collapse_albums(collected.values()))} posts collected...")

            if added == 0:
                stagnant += 1
                if stagnant >= self.MAX_STAGNANT_PAGES:
                    break
            else:
                stagnant = 0

            # Page backward using the oldest date in this batch. If it doesn't
            # move us further back, we're at the end — bail rather than loop.
            next_date = self._min_date(history)
            if not next_date or next_date >= cur_date:
                break
            cur_date = next_date
            time.sleep(self.PAGE_DELAY_SECONDS)

        # Collapse album siblings into logical posts, oldest -> newest (the
        # analyzer's post_index convention: 1 = oldest). When capped, keep the
        # most recent `max_posts`.
        posts = self._collapse_albums(collected.values())
        if max_posts and len(posts) > max_posts:
            posts = posts[-max_posts:]

        results = [self._extract_post(m, i) for i, m in enumerate(posts, start=1)]

        print(f"[+] Finished: {len(results)} posts scraped from @{self.target}.")
        print(
            "[i] Note: Bale exposes no comments, so comment-based demand signals "
            "will be empty in the report."
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
