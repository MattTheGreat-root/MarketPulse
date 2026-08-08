"""
Authenticated Telegram scraper for MarketPulse (MTProto / Telethon).

WHY THIS EXISTS
---------------
``TelegramScraper`` (the sibling in this folder) reads Telegram's anonymous
public web preview at ``t.me/s/<channel>``. That surface is ban-proof but
structurally exposes **no comments** — a channel post's "comments" are actually
replies living in the channel's *linked discussion group*, which the preview
never serves. So the analyzer's comment intelligence (buyer-intent demand
signals + the Groq AI pass) comes back empty for Telegram.

This backend logs in with a real (burner) account over MTProto and therefore
CAN read those discussion-group replies. It is **additive and opt-in**: the
preview scraper stays the no-account default; main.py only routes here when the
operator asked for comments AND Telegram API credentials are present. Everything
else — the CSV schema, price/engagement semantics, downstream analysis — is
identical to the preview scraper, so nothing downstream changes.

HOW COMMENTS ARE FETCHED
------------------------
Telethon resolves the linked discussion group automatically: for a channel post
with id ``P``, ``client.iter_messages(channel, reply_to=P)`` yields exactly the
comments on that post. We only ask for posts that actually have a comment thread
(``msg.replies.replies > 0``) so we don't spam pointless requests, and we cap the
number of comments per post (mirroring ``RubinoScraper``'s 10) to keep runs fast
and gentle on the account.

SETUP (one-time): create an app at https://my.telegram.org (API development
tools) with the burner, then put in ``.env``::

    TELEGRAM_API_ID=1234567
    TELEGRAM_API_HASH=abcdef0123456789abcdef0123456789
    TELEGRAM_PHONE=+98...

First run prints a login code prompt (the code arrives in the Telegram app on the
burner); the session is saved to ``auth/telegram_<phone>.session`` and reused
silently afterward.
"""

import asyncio
import os
from datetime import datetime

from core.base_scraper import BaseScraper
from core.parsers import parse_engagement_text


class TelegramAuthedScraper(BaseScraper):
    # Per-post comment cap. Matches RubinoScraper so every platform's CSV carries
    # a comparable comment depth, and keeps MTProto call volume bounded.
    MAX_COMMENTS_PER_POST = 10
    # Politeness: small pause between per-post comment fetches to protect the
    # (burner) account from flood-waits on large channels.
    PER_POST_DELAY_SECONDS = 0.3

    def __init__(self, driver, target, output_dir="data",
                 api_id=None, api_hash=None, phone=None, session_dir="auth"):
        # ``driver`` is accepted only to satisfy the BaseScraper contract; this
        # scraper is pure MTProto and never touches Selenium. main.py passes None.
        super().__init__(driver, target, output_dir)

        # Accept "@channel", "https://t.me/channel", "t.me/s/channel", or bare.
        self.target = self._normalize_target(target)

        # Credentials: explicit args win, else fall back to the environment.
        self.api_id = api_id or os.getenv("TELEGRAM_API_ID")
        self.api_hash = api_hash or os.getenv("TELEGRAM_API_HASH")
        self.phone = phone or os.getenv("TELEGRAM_PHONE")

        # Timestamped output name so MarketAnalyzer / ClientPackager (which glob
        # `{username}_*.csv`) pick up the freshest run — identical to the preview
        # scrapers.
        safe_target = "".join(c for c in self.target if c.isalnum() or c in ("_", "-"))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_path = os.path.join(self.output_dir, f"{safe_target}_{ts}.csv")

        # One persistent session file per phone, kept out of git (see .gitignore).
        if not os.path.exists(session_dir):
            os.makedirs(session_dir)
        safe_phone = "".join(c for c in (self.phone or "anon") if c.isalnum())
        self.session_path = os.path.join(session_dir, f"telegram_{safe_phone}")

    # ---------------------------------------------------------------- utilities
    @staticmethod
    def creds_available() -> bool:
        """True iff the three MTProto credentials are set — lets main.py decide
        whether to route here or fall back to the anonymous preview scraper."""
        return all(os.getenv(k) for k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE"))

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
        return t.split("/")[0].split("?")[0]

    @staticmethod
    def _sum_reactions(msg) -> int:
        """Sum reaction counts on a post: [👍×5, ❤×3] -> 8 (0 if none)."""
        r = getattr(msg, "reactions", None)
        results = getattr(r, "results", None) if r else None
        total = 0
        for rc in results or []:
            try:
                total += int(getattr(rc, "count", 0) or 0)
            except (TypeError, ValueError):
                continue
        return total

    @staticmethod
    def _reply_count(msg) -> int:
        """The post's comment-thread size (0 if the post has no comments)."""
        rep = getattr(msg, "replies", None)
        if rep is not None:
            try:
                return int(getattr(rep, "replies", 0) or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    @staticmethod
    def _sender_handle(m) -> str:
        """A readable author label for a comment: @username, else full name,
        else a channel title, else 'anonymous'. Matches the 'user: text' shape
        the analyzer expects (core/analyzer.py:_format_comments_for_nlp)."""
        s = getattr(m, "sender", None)
        if s is not None:
            uname = getattr(s, "username", None)
            if uname:
                return uname
            name = ((getattr(s, "first_name", "") or "") + " "
                    + (getattr(s, "last_name", "") or "")).strip()
            if name:
                return name
            title = getattr(s, "title", None)  # channels commenting as themselves
            if title:
                return title
        return "anonymous"

    # ---------------------------------------------------------- comment fetching
    async def _fetch_comments(self, client, entity, post_id: int) -> list:
        """Return up to MAX_COMMENTS_PER_POST 'user: text' lines for one post.

        Newlines inside a single comment are collapsed to spaces so the CSV
        contract holds: the analyzer treats ONE line == ONE comment (it splits
        the cell on '\\n' in _offline_comment_signals / _format_comments_for_nlp).
        Posts without a discussion thread raise inside Telethon; we swallow that
        and return [] so scraping continues.
        """
        lines = []
        try:
            async for c in client.iter_messages(
                entity, reply_to=post_id, limit=self.MAX_COMMENTS_PER_POST
            ):
                text = " ".join((c.text or "").split()).strip()
                if not text:
                    continue  # skip service messages / media-only replies
                lines.append(f"{self._sender_handle(c)}: {text}")
        except Exception:
            # MsgIdInvalidError (no linked thread), flood-wait leftovers, etc.
            return []
        return lines

    def _extract_post(self, msg, idx: int, comments: list) -> dict:
        """Map a Telethon channel message to the shared CSV schema (identical
        columns to TelegramScraper._extract_post, with `comments` now filled)."""
        description = msg.text or ""
        views = int(getattr(msg, "views", 0) or 0)
        reactions = self._sum_reactions(msg)
        replies = self._reply_count(msg)

        # Engagement = reach (views) + active signals (reactions + comments),
        # consistent with the preview scraper's philosophy.
        engagement = views + reactions + replies

        price = parse_engagement_text(description)["price"] if description else "None"
        posted_at = msg.date.isoformat() if getattr(msg, "date", None) else ""

        return {
            "post_index": idx,
            "description": description,
            "price": price,
            "engagement": engagement,
            "comments": "\n".join(comments),
            "views": views,
            "reactions": reactions,
            "posted_at": posted_at,
            "post_url": f"https://t.me/{self.target}/{msg.id}",
        }

    # --------------------------------------------------------------- async core
    async def _async_run(self, max_posts=None) -> list:
        # Imported lazily so the whole project doesn't hard-depend on Telethon
        # unless this authenticated backend is actually used.
        from telethon import TelegramClient
        from telethon.errors import FloodWaitError

        client = TelegramClient(self.session_path, int(self.api_id), self.api_hash)
        # start() runs the interactive login on first use (code prompt, and a
        # 2FA password prompt if the burner has one), then reuses the session.
        await client.start(phone=self.phone)

        results = []
        try:
            try:
                entity = await client.get_entity(self.target)
            except Exception as e:
                print(f"[!] Could not resolve Telegram channel '{self.target}': {e}")
                return []

            title = getattr(entity, "title", None) or self.target
            print(f"[+] Authenticated to @{self.target} ({title}). Reading posts...")

            posts = []  # (message, [comment lines]) newest-first from Telethon
            async for msg in client.iter_messages(entity, limit=max_posts):
                if getattr(msg, "action", None) is not None:
                    continue  # skip service messages (pins, joins, etc.)
                comments = []
                if self._reply_count(msg) > 0:
                    try:
                        comments = await self._fetch_comments(client, entity, msg.id)
                    except FloodWaitError as e:
                        print(f"[!] Flood-wait {e.seconds}s while reading comments "
                              f"on post {msg.id}; skipping its comments.")
                    await asyncio.sleep(self.PER_POST_DELAY_SECONDS)
                posts.append((msg, comments))
                if len(posts) % 20 == 0:
                    print(f"  -> {len(posts)} posts read...")

            # Telethon yields newest-first; number oldest->1 so post_index
            # increases with time (the convention _momentum_stats relies on).
            posts.reverse()
            results = [self._extract_post(m, i, c) for i, (m, c) in enumerate(posts, start=1)]
        finally:
            await client.disconnect()

        with_comments = sum(1 for r in results if r["comments"])
        print(f"[+] Finished: {len(results)} posts from @{self.target} "
              f"({with_comments} with comments).")
        if results and with_comments == 0:
            print("[i] No comments found — this channel may have no linked "
                  "discussion group, or its posts have no replies yet.")
        return results

    # ---------------------------------------------------------- BaseScraper API
    def navigate_to_page(self) -> bool:
        # Reachability is validated inside the authenticated async flow
        # (get_entity); nothing to pre-check over plain HTTP here.
        return True

    def scrape_all_posts(self, max_posts=None) -> list:
        # Provided for interface completeness; run() is the real entry point.
        return asyncio.run(self._async_run(max_posts=max_posts))

    def run(self, max_posts=None):
        """Sync lifecycle wrapper: drive the async MTProto flow to completion,
        then persist via the shared CSV/XLSX writer."""
        if not (self.api_id and self.api_hash and self.phone):
            print("[!] Telegram API credentials missing "
                  "(TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE).")
            return []
        print(f"[*] Starting authenticated Telegram extraction for @{self.target}...")
        try:
            results = asyncio.run(self._async_run(max_posts=max_posts))
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[!] Authenticated Telegram scraping failed for @{self.target}: {e}")
            return []
        if results:
            self.save_to_csv(results)
        return results
