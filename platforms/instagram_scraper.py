"""
Instagram (اینستاگرام) profile scraper for MarketPulse.

Instagram is the biggest social-commerce channel for Iranian shops, but it is
also the harshest environment to scrape: the private mobile API bans fresh
accounts within minutes, and even careful logged-in automation risks the
account. To avoid ANY account-ban exposure, this scraper reads Instagram
*anonymously* via instaloader — there is no login, so there is literally no
account to ban.

The trade-off (accepted deliberately): anonymous access reliably exposes a
public profile's posts, captions, like/comment COUNTS, timestamps and hashtags,
but NOT the comment TEXT (Instagram gates the comments endpoint behind login).
So — exactly like the Bale and Telegram web previews — the ``comments`` column
is left empty and the analyzer's comment-based demand signals come back empty.
Everything else (pricing, engagement, categories, momentum, competitor
comparison) works fully from the captions and counts.

This mirrors ``BaleScraper`` on purpose: pure HTTP (no Selenium driver), same
CSV schema, so the whole downstream pipeline (analyzer, classifier, report,
packager) consumes it unchanged.

Anonymous access is inherently fragile: Instagram increasingly login-walls and
geo-rate-limits anonymous requests. When that happens the scraper degrades
gracefully — it prints a clear reason and returns no rows rather than hammering
the endpoint (which would only deepen a temporary block). Retrying later or from
a cleaner IP usually helps.
"""

import itertools
import os
import time
from datetime import datetime

from core.base_scraper import BaseScraper
from core.parsers import parse_engagement_text


class InstagramScraper(BaseScraper):
    # Politeness / safety knobs. Anonymous Instagram is the rate-limit-prone
    # part, so we sleep between posts and cap unbounded (pro / max_posts=None)
    # runs to a sane ceiling to protect the IP rather than pulling an entire
    # back-catalogue in one anonymous burst.
    PER_POST_DELAY_SECONDS = 1.2
    ANON_SAFE_CAP = 60

    def __init__(self, driver, target, output_dir="data"):
        # ``driver`` is accepted only to satisfy the BaseScraper contract; this
        # scraper is pure HTTP (instaloader) and never touches Selenium. main.py
        # passes None.
        super().__init__(driver, target, output_dir)

        self.target = self._normalize_target(target)

        # Match the Telegram/Bale/Rubino timestamped naming so MarketAnalyzer /
        # ClientPackager (which glob `{username}_*.csv` / `.xlsx`) pick up the
        # freshest run.
        safe_target = "".join(c for c in self.target if c.isalnum() or c in ("_", "-"))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_path = os.path.join(self.output_dir, f"{safe_target}_{ts}.csv")

        # Populated by navigate_to_page() so scrape_all_posts() doesn't re-resolve.
        self._loader = None
        self._profile = None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _normalize_target(target: str) -> str:
        """Turn @name / instagram.com/name / https://instagram.com/name/ into 'name'."""
        t = (target or "").strip()
        t = t.replace("https://", "").replace("http://", "")
        for prefix in (
            "www.instagram.com/",
            "instagram.com/",
            "www.instagr.am/",
            "instagr.am/",
        ):
            if t.startswith(prefix):
                t = t[len(prefix):]
                break
        t = t.lstrip("@").strip("/")
        # A handle can't contain a slash/query; keep only the handle segment.
        return t.split("/")[0].split("?")[0]

    def _build_loader(self):
        """Create a metadata-only, zero-disk, anonymous Instaloader."""
        import instaloader

        return instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            quiet=True,
        )

    @staticmethod
    def _safe_int(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _extract_post(self, post, idx: int) -> dict:
        """Map one instaloader Post to the shared CSV schema."""
        try:
            description = post.caption or ""
        except Exception:
            description = ""

        likes = self._safe_int(getattr(post, "likes", 0))
        comment_count = self._safe_int(getattr(post, "comments", 0))

        # Video view count exists only on video posts and can require an extra
        # metadata fetch; guard it and default to 0 so we never trigger an extra
        # request or crash on an image post.
        views = 0
        try:
            if getattr(post, "is_video", False):
                views = self._safe_int(getattr(post, "video_view_count", 0))
        except Exception:
            views = 0

        # Engagement = likes + comments, matching the "likes + comments"
        # philosophy the Rubino scraper uses. (Instagram exposes no separate
        # reach figure for image posts.)
        engagement = likes + comment_count

        price = parse_engagement_text(description)["price"] if description else "None"

        try:
            posted_at = post.date_utc.isoformat()
        except Exception:
            posted_at = ""

        shortcode = getattr(post, "shortcode", "") or ""
        post_url = (
            f"https://www.instagram.com/p/{shortcode}/"
            if shortcode
            else f"https://www.instagram.com/{self.target}/"
        )

        return {
            "post_index": idx,
            "description": description,
            "price": price,
            "engagement": engagement,
            "comments": "",  # anonymous access exposes no comment text
            "likes": likes,
            "comments_count": comment_count,
            "views": views,
            "posted_at": posted_at,
            "post_url": post_url,
        }

    # ---------------------------------------------------------- BaseScraper API
    def navigate_to_page(self) -> bool:
        try:
            import instaloader
            from instaloader.exceptions import (
                ConnectionException,
                LoginRequiredException,
                ProfileNotExistsException,
                QueryReturnedBadRequestException,
                TooManyRequestsException,
            )
        except ImportError:
            print("[!] instaloader is not installed. Run: pip install instaloader")
            return False

        print(f"[*] Looking up Instagram profile: @{self.target}")
        try:
            self._loader = self._build_loader()
            self._profile = instaloader.Profile.from_username(
                self._loader.context, self.target
            )
        except ProfileNotExistsException:
            print(f"[!] Instagram profile '@{self.target}' does not exist.")
            return False
        except (
            LoginRequiredException,
            QueryReturnedBadRequestException,
            TooManyRequestsException,
        ) as e:
            print(
                f"[!] Instagram refused anonymous access for '@{self.target}' "
                f"({type(e).__name__}) — it is login-walling or rate-limiting this "
                "IP. Try again later or from a cleaner IP."
            )
            return False
        except ConnectionException as e:
            print(f"[!] Could not reach Instagram for '@{self.target}': {e}")
            return False
        except Exception as e:
            print(f"[!] Unexpected error resolving '@{self.target}': {e}")
            return False

        if getattr(self._profile, "is_private", False):
            print(
                f"[!] '@{self.target}' is a private account; anonymous scraping "
                "cannot read its posts. Skipping."
            )
            return False

        try:
            total = self._profile.mediacount
        except Exception:
            total = "?"
        print(f"[+] Found @{self.target} — {total} posts total.")
        return True

    def scrape_all_posts(self, max_posts=None) -> list:
        from instaloader.exceptions import (
            ConnectionException,
            LoginRequiredException,
            TooManyRequestsException,
        )

        # navigate_to_page() should have primed the profile; fall back defensively.
        if self._profile is None:
            if not self.navigate_to_page():
                return []

        # Anonymous is rate-limit-prone; cap an unbounded (pro) run to protect
        # the IP instead of trying to pull the whole back-catalogue at once.
        limit = max_posts if max_posts is not None else self.ANON_SAFE_CAP
        if max_posts is None:
            print(
                f"[i] Anonymous Instagram: capping this run at {self.ANON_SAFE_CAP} "
                "posts to stay under the rate limit (pro/all is not safe anonymously)."
            )

        print(f"[*] Scraping up to {limit} posts from @{self.target} (anonymous)...")

        collected = []
        try:
            for post in itertools.islice(self._profile.get_posts(), limit):
                collected.append(post)
                if len(collected) < limit:
                    time.sleep(self.PER_POST_DELAY_SECONDS)
        except (LoginRequiredException, TooManyRequestsException):
            print(
                f"[!] Instagram login-walled/rate-limited us after {len(collected)} "
                "posts; stopping gracefully with what we have."
            )
        except ConnectionException as e:
            print(
                f"[!] Instagram connection dropped after {len(collected)} posts "
                f"({e}); stopping gracefully."
            )
        except Exception as e:
            print(f"[!] Stopped after {len(collected)} posts due to: {e}")

        # Instagram yields newest-first; reverse so oldest = post_index 1 (the
        # analyzer's momentum convention, matching Bale/Telegram-authed).
        collected.reverse()
        results = [self._extract_post(p, i) for i, p in enumerate(collected, start=1)]

        print(f"[+] Finished: {len(results)} posts scraped from @{self.target}.")
        print(
            "[i] Note: anonymous Instagram exposes no comment text, so comment-based "
            "demand signals will be empty in the report (same as the Bale preview)."
        )
        return results

    def run(self, max_posts=None):
        """Lifecycle override: no browser/driver to tear down for HTTP scraping."""
        print(f"[*] Starting Instagram extraction for @{self.target}...")
        if not self.navigate_to_page():
            print(f"[!] Failed to access Instagram profile @{self.target}.")
            return []
        results = self.scrape_all_posts(max_posts=max_posts)
        self.save_to_csv(results)
        return results
