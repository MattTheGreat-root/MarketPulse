import sys
import os

# Force Python to recognize the MarketPulse root directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.browser_manager import BrowserManager
from auth.rubino_auth import RubikaAuth
from platforms.rubino_scraper import RubinoScraper
from core.analyzer import MarketAnalyzer

def print_banner():
    print("""
    =========================================
       MarketPulse Data Automation Engine
    =========================================
    """)

def main():
    print_banner()

    # 1. Interactive Inputs
    target_username = input("[?] Enter the target Rubino username (without @): ").strip()
    if not target_username:
        print("[!] Username cannot be empty. Exiting.")
        sys.exit(1)

    max_posts_input = input("[?] Max posts to scrape (press ENTER to scrape all): ").strip()
    max_posts = int(max_posts_input) if max_posts_input.isdigit() else None

    print(f"\n[*] Initializing pipeline for Rubino target: @{target_username}")
    
    # Tier 1: Driver Factory
    manager = BrowserManager(platform_name="rubino")
    raw_driver = manager.get_driver()
    
    try:
        # Tier 2: Authentication Strategy
        auth = RubikaAuth(driver=raw_driver)
        authenticated_driver = auth.verify_session()
        
        # Tier 3: Scraping Strategy
        scraper = RubinoScraper(driver=authenticated_driver, target=target_username)
        scraper.run(max_posts=max_posts)
        
        # Tier 4: Analysis Strategy (Runs automatically after scraping)
        analyzer = MarketAnalyzer()
        trends = analyzer.calculate_trends(target_username=target_username, top_n=5)
        
        if not trends.empty:
            print("\n================ TOP TRENDING POSTS ================")
            print(trends[['post_index', 'price', 'likes', 'comments', 'engagement_score']].to_string(index=False))
            print("====================================================")
        else:
            print("\n[!] No trend data could be calculated.")
            
    except KeyboardInterrupt:
        print("\n[!] Pipeline interrupted by user.")
    except Exception as e:
        print(f"\n[!] Pipeline encountered a fatal error: {e}")
    finally:
        print("[*] Closing browser session and cleaning up.")
        raw_driver.quit()
        sys.exit(0)

if __name__ == "__main__":
    main()