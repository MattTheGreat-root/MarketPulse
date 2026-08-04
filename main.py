import sys
import os
from dotenv import load_dotenv

# Load environment variables from the .env file in the root directory
load_dotenv()

# Force Python to recognize the MarketPulse root directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.browser_manager import BrowserManager
from auth.rubino_auth import RubikaAuth
from platforms.rubino_scraper import RubinoScraper
from platforms.telegram_scraper import TelegramScraper
from platforms.bale_scraper import BaleScraper
from core.analyzer import MarketAnalyzer, CompetitorComparator
from core.report_generator import ReportGenerator
from core.packager import ClientPackager


# ---------------------------------------------------------------------------
# Run modes. Each mode is a product tier and fully determines the run so the
# operator never answers a questionnaire — just picks a mode, a platform, and
# the target(s).
#
#   mini   - FREE lead magnet. 15 posts, at most 1 competitor, mini report,
#            no comments/NLP, no zip. This is what you send in cold outreach.
#   normal - Paid full report. More posts + competitors, full report, comments
#            + AI comment analysis on Rubino (Telegram/Bale previews expose no
#            comments yet), no zip.
#   pro    - Everything the engine can do: max posts, all competitors, comments
#            + NLP, full report, packaged client .zip deliverable.
#
# `comments` here means "attempt comment-based AI analysis". It only has an
# effect on platforms whose scraper actually captures comments (currently
# Rubino); Telegram/Bale are auto-skipped until their scrapers grow comments.
# ---------------------------------------------------------------------------
MODES = {
    "mini": {
        "label": "MINI (free lead magnet)",
        "max_posts": 15,
        "max_competitors": 1,
        "comments": False,
        "report": "mini",
        "zip": False,
    },
    "normal": {
        "label": "NORMAL (full report)",
        "max_posts": 100,
        "max_competitors": 3,
        "comments": True,
        "report": "full",
        "zip": False,
    },
    "pro": {
        "label": "PRO (maximum)",
        "max_posts": None,       # None = all available
        "max_competitors": None,  # None = all given
        "comments": True,
        "report": "full",
        "zip": True,
    },
}

PLATFORMS = {"r": "rubino", "t": "telegram", "b": "bale"}

# Platforms whose scraper currently captures comments (so AI comment analysis
# can run). Telegram/Bale web previews don't expose comments yet.
COMMENT_CAPABLE = {"rubino"}


def print_banner():
    print("""
    =========================================
       MarketPulse Data & Intelligence Engine
    =========================================
    """)


def ask(prompt, default=None):
    val = input(prompt).strip()
    return val if val else default


def scrape_profile(username, max_posts, platform="rubino"):
    """Scrape a single profile/channel. Returns True on success."""
    if platform == "telegram":
        return _scrape_telegram(username, max_posts)
    if platform == "bale":
        return _scrape_bale(username, max_posts)
    return _scrape_rubino(username, max_posts)


def _scrape_bale(username, max_posts):
    """Scrape a public Bale channel via its web preview (no account needed)."""
    try:
        print(f"\n[*] Initializing Bale scraping pipeline for channel: @{username}")
        # No Selenium driver required; BaleScraper is pure HTTP.
        scraper = BaleScraper(driver=None, target=username)
        results = scraper.run(max_posts=max_posts)
        return bool(results)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[!] Bale scraping failed for @{username}: {e}")
        return False


def _scrape_telegram(username, max_posts):
    """Scrape a public Telegram channel via its web preview (no account needed)."""
    try:
        print(f"\n[*] Initializing Telegram scraping pipeline for channel: @{username}")
        # No Selenium driver required; TelegramScraper is pure HTTP.
        scraper = TelegramScraper(driver=None, target=username)
        results = scraper.run(max_posts=max_posts)
        return bool(results)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[!] Telegram scraping failed for @{username}: {e}")
        return False


def _scrape_rubino(username, max_posts):
    """Scrape a single profile. Returns True on success."""
    raw_driver = None
    try:
        print(f"\n[*] Initializing scraping pipeline for Rubino target: @{username}")
        manager = BrowserManager(platform_name="rubino")
        raw_driver = manager.get_driver()

        auth = RubikaAuth(driver=raw_driver)
        authenticated_driver = auth.verify_session()

        scraper = RubinoScraper(driver=authenticated_driver, target=username)
        scraper.run(max_posts=max_posts)
        return True
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[!] Scraping failed for @{username}: {e}")
        return False
    finally:
        if raw_driver:
            print("[*] Closing browser session.")
            raw_driver.quit()


def analyze_profile(analyzer, username, run_nlp, label="profile"):
    try:
        insights = analyzer.analyze_profile(username, top_n=5, run_nlp=run_nlp)
        if insights.get("has_data"):
            eng = insights["engagement"]
            print(f"  -> [{label}] @{username}: {insights['post_count']} posts | "
                  f"avg engagement {eng['mean']:.0f} | star: {insights['categories'].get('star_category')}")
        return insights
    except FileNotFoundError as e:
        print(f"  -> [!] {e}")
        return None


# ---------------------------------------------------------------------------
# Input handling: minimal interactive prompts, with optional CLI args as a
# fast path.  Usage:
#     python main.py [mode] [platform] [client] [comp1,comp2] [saved]
# Any missing piece is asked for; extras like posts/zip/nlp come from the mode.
# ---------------------------------------------------------------------------
def resolve_mode(raw):
    raw = (raw or "").strip().lower()
    aliases = {"m": "mini", "n": "normal", "p": "pro"}
    raw = aliases.get(raw, raw)
    return raw if raw in MODES else None


def resolve_platform(raw):
    raw = (raw or "").strip().lower()
    if raw in PLATFORMS:            # r / t / b
        return PLATFORMS[raw]
    if raw in PLATFORMS.values():   # full name
        return raw
    return None


def gather_run_config(argv):
    """Build the run config from CLI args first, prompting only for what's
    missing. Returns a dict describing the whole run."""
    args = list(argv)

    # --- mode ---
    mode = resolve_mode(args[0]) if len(args) >= 1 else None
    while not mode:
        mode = resolve_mode(ask("[?] Mode: mini (free) / normal / pro: ", "mini"))
        if not mode:
            print("    Please enter one of: mini, normal, pro.")
    cfg = dict(MODES[mode])
    cfg["mode"] = mode

    # --- platform ---
    platform = resolve_platform(args[1]) if len(args) >= 2 else None
    while not platform:
        platform = resolve_platform(ask("[?] Platform: r (rubino) / b (bale) / t (telegram): ", "r"))
        if not platform:
            print("    Please enter one of: r, b, t.")
    cfg["platform"] = platform

    # --- client ---
    client = args[2] if len(args) >= 3 else None
    while not client:
        client = ask(f"[?] Client {platform} username/channel (without @): ")
        if not client:
            print("    Client cannot be empty.")
    cfg["client"] = client.lstrip("@")

    # --- competitors (respect the mode cap) ---
    if len(args) >= 4:
        comps_raw = args[3]
    else:
        cap = cfg["max_competitors"]
        cap_txt = "1 max" if cap == 1 else (f"up to {cap}" if cap else "any number")
        comps_raw = ask(f"[?] Competitor(s), comma-separated ({cap_txt}, ENTER to skip): ", "")
    competitors = [c.strip().lstrip("@") for c in (comps_raw or "").split(",") if c.strip()]
    if cfg["max_competitors"] is not None and len(competitors) > cfg["max_competitors"]:
        dropped = competitors[cfg["max_competitors"]:]
        competitors = competitors[:cfg["max_competitors"]]
        print(f"[i] {cfg['label']} allows {cfg['max_competitors']} competitor(s); "
              f"ignoring: {', '.join(dropped)}")
    cfg["competitors"] = competitors

    # --- fresh vs saved data ---
    saved_flag = any(a.strip().lower() in ("saved", "--saved", "-s") for a in args[4:])
    if saved_flag:
        cfg["scrape"] = False
    else:
        # Only ask if not already told via args; default is to scrape fresh.
        if len(args) >= 5:
            cfg["scrape"] = True
        else:
            ans = ask("[?] Scrape fresh data? (Y/n — 'n' reuses latest saved CSVs): ", "y").lower()
            cfg["scrape"] = not ans.startswith("n")

    return cfg


def print_plan(cfg):
    comment_note = ""
    if cfg["comments"] and cfg["platform"] not in COMMENT_CAPABLE:
        comment_note = f"  (skipped: {cfg['platform']} preview has no comments yet)"
    print(f"\n[=] Run plan")
    print(f"    Mode        : {cfg['label']}")
    print(f"    Platform    : {cfg['platform']}")
    print(f"    Client      : @{cfg['client']}")
    print(f"    Competitors : {', '.join('@'+c for c in cfg['competitors']) or '—'}")
    print(f"    Posts/target: {cfg['max_posts'] if cfg['max_posts'] is not None else 'all'}")
    print(f"    Comments/AI : {'yes' if cfg['comments'] else 'no'}{comment_note}")
    print(f"    Report      : {cfg['report']}")
    print(f"    Package .zip: {'yes' if cfg['zip'] else 'no'}")
    print(f"    Data        : {'scrape fresh' if cfg['scrape'] else 'reuse latest saved'}\n")


def main():
    print_banner()

    cfg = gather_run_config(sys.argv[1:])
    print_plan(cfg)

    platform = cfg["platform"]
    client_username = cfg["client"]
    competitor_usernames = cfg["competitors"]
    all_usernames = [client_username] + competitor_usernames

    # Comment-based AI analysis: requested by the mode AND supported by the
    # platform's scraper. Telegram/Bale previews have no comments (yet), so it
    # is skipped there automatically instead of silently doing nothing.
    run_nlp = cfg["comments"] and platform in COMMENT_CAPABLE
    if cfg["comments"] and not run_nlp:
        print(f"[i] {platform.capitalize()} has no comments; AI comment analysis skipped.")

    is_mini = cfg["report"] == "mini"

    # ----------------------------------------------------------- scrape phase
    if cfg["scrape"]:
        for uname in all_usernames:
            ok = scrape_profile(uname, cfg["max_posts"], platform=platform)
            if not ok and uname == client_username:
                print("[!] Client scraping failed. Aborting.")
                sys.exit(1)
    else:
        print("[*] Skipping scraper. Using latest saved data for all profiles.")

    # --------------------------------------------------------- analysis phase
    print("\n[*] Running analysis...")
    analyzer = MarketAnalyzer()

    client_insights = analyze_profile(analyzer, client_username, run_nlp, label="CLIENT")
    if not client_insights or not client_insights.get("has_data"):
        print("[!] No usable client data found. Make sure the client was scraped first.")
        sys.exit(1)

    competitor_insights = []
    for comp in competitor_usernames:
        # Competitors: skip the (costly) AI pass by default; the offline signals
        # and structured metrics are enough for a strong comparison.
        ci = analyze_profile(analyzer, comp, run_nlp=False, label="COMPETITOR")
        if ci and ci.get("has_data"):
            competitor_insights.append(ci)

    # ------------------------------------------------------- comparison phase
    comparison = None
    if competitor_insights:
        print("\n[*] Building competitive comparison and strategic advice...")
        comparison = CompetitorComparator().compare(client_insights, competitor_insights)
        for i, a in enumerate(comparison.get("advice", []), 1):
            print(f"   {i}. {a}")

    # ----------------------------------------------------------- report phase
    print("\n[*] Generating client report...")
    reporter = ReportGenerator()
    if is_mini:
        paths = reporter.generate_mini_report(
            client_insights=client_insights,
            comparison=comparison,
            competitor_insights=competitor_insights,
            make_pdf=True,
        )
    else:
        paths = reporter.generate_report(
            client_insights=client_insights,
            comparison=comparison,
            competitor_insights=competitor_insights,
            make_pdf=True,
        )

    # ---------------------------------------------------------- package phase
    if cfg["zip"]:
        packager = ClientPackager()
        packager.package_deliverables(
            target_username=client_username,
            competitor_usernames=competitor_usernames,
            mini=is_mini,
        )

    print("\n[+] Done. Report ready for delivery.")
    if paths.get("pdf"):
        print(f"    PDF:  {paths['pdf']}")
    print(f"    HTML: {paths['html']}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Pipeline interrupted by user.")
        sys.exit(0)
