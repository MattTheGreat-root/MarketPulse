import argparse
import sys
from core.browser_manager import BrowserManager
from auth.rubino_auth import RubikaAuth
from platforms.rubino_scraper import RubinoScraper

def print_banner():
    print("""
    =========================================
       MarketPulse Data Automation Engine
    =========================================
    """)

def main():
    parser = argparse.ArgumentParser(description="MarketPulse Multi-Platform Scraper")
    parser.add_argument('--platform', type=str, choices=['rubino'], required=True, help="Target platform to scrape (e.g., rubino)")
    parser.add_argument('--target', type=str, required=True, help="Target username or channel ID")
    parser.add_argument('--max-posts', type=int, default=None, help="Maximum number of posts to scrape")
    
    args = parser.parse_args()
    print_banner()

    if args.platform == 'rubino':
        print(f"[*] Initializing pipeline for Rubino target: @{args.target}")
        
        # Tier 1: Driver Factory
        manager = BrowserManager(platform_name="rubino")
        raw_driver = manager.get_driver()
        
        try:
            # Tier 2: Authentication Strategy
            auth = RubikaAuth(driver=raw_driver)
            authenticated_driver = auth.verify_session()
            
            # Tier 3: Scraping Strategy
            scraper = RubinoScraper(driver=authenticated_driver, target=args.target)
            scraper.run(max_posts=args.max_posts)
            
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