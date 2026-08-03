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
from core.analyzer import MarketAnalyzer, CompetitorComparator
from core.report_generator import ReportGenerator
from core.packager import ClientPackager


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
    return _scrape_rubino(username, max_posts)


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


def main():
    print_banner()

    # ---------------------------------------------------------------- inputs
    platform_input = ask(
        "[?] Platform: rubino or telegram? (rubino/telegram): ", "rubino"
    ).lower()
    platform = "telegram" if platform_input.startswith("t") else "rubino"

    if platform == "telegram":
        client_username = ask("[?] Enter the CLIENT Telegram channel (without @): ")
    else:
        client_username = ask("[?] Enter the CLIENT Rubino username (without @): ")
    if not client_username:
        print("[!] Client username cannot be empty. Exiting.")
        sys.exit(1)

    competitors_raw = ask(
        "[?] Enter COMPETITOR usernames (comma-separated, or ENTER to skip): ", ""
    )
    competitor_usernames = [c.strip() for c in competitors_raw.split(",") if c.strip()]

    mode = ask("[?] Scrape fresh data? (y/n - 'n' analyzes latest saved files): ", "n").lower()
    if platform == "telegram":
        # The public web preview exposes no comments, so comment-level AI analysis
        # has nothing to work on. Skip it automatically to save time and API cost.
        run_nlp = False
        print("[i] Telegram preview has no comments; AI comment analysis is skipped.")
    else:
        run_nlp_input = ask("[?] Run AI comment analysis (needs GROQ_API_KEY)? (y/n): ", "y").lower()
        run_nlp = (run_nlp_input == "y")
    make_pdf_input = ask("[?] Generate PDF report? (y/n): ", "y").lower()
    make_pdf = (make_pdf_input == "y")
    make_zip_input = ask("[?] Package everything into a client .zip? (y/n): ", "y").lower()
    make_zip = (make_zip_input == "y")
    report_type_input = ask("[?] Report type: full (detailed) or mini (~4 pages)? (full/mini): ", "full").lower()
    is_mini = report_type_input == "mini"

    all_usernames = [client_username] + competitor_usernames

    # ----------------------------------------------------------- scrape phase
    if mode == "y":
        max_posts_input = ask("[?] Max posts per profile (ENTER = all): ", None)
        max_posts = int(max_posts_input) if (max_posts_input and max_posts_input.isdigit()) else None

        for uname in all_usernames:
            ok = scrape_profile(uname, max_posts, platform=platform)
            if not ok and uname == client_username:
                print("[!] Client scraping failed. Aborting.")
                sys.exit(1)
    else:
        print("\n[*] Skipping scraper. Using latest saved data for all profiles.")

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
            make_pdf=make_pdf,
        )
    else:
        paths = reporter.generate_report(
            client_insights=client_insights,
            comparison=comparison,
            competitor_insights=competitor_insights,
            make_pdf=make_pdf,
        )

    # ---------------------------------------------------------- package phase
    if make_zip:
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
