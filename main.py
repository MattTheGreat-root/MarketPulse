import sys
import os
import json
import pandas as pd
from dotenv import load_dotenv

# Load environment variables from the .env file in the root directory
load_dotenv()

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

    # 1. Target Input
    target_username = input("[?] Enter the target Rubino username (without @): ").strip()
    if not target_username:
        print("[!] Username cannot be empty. Exiting.")
        sys.exit(1)

    # 2. Mode Selection
    mode = input("[?] Do you want to scrape new data? (y/n - 'n' will only analyze the latest file): ").strip().lower()
    
    raw_driver = None

    try:
        if mode == 'y':
            max_posts_input = input("[?] Max posts to scrape (press ENTER to scrape all): ").strip()
            max_posts = int(max_posts_input) if max_posts_input.isdigit() else None

            print(f"\n[*] Initializing scraping pipeline for Rubino target: @{target_username}")
            
            # Tier 1: Driver Factory
            manager = BrowserManager(platform_name="rubino")
            raw_driver = manager.get_driver()
            
            # Tier 2: Authentication Strategy
            auth = RubikaAuth(driver=raw_driver)
            authenticated_driver = auth.verify_session()
            
            # Tier 3: Scraping Strategy
            scraper = RubinoScraper(driver=authenticated_driver, target=target_username)
            scraper.run(max_posts=max_posts)
        else:
            print(f"\n[*] Skipping scraper. Proceeding directly to analysis for @{target_username}...")

        # Tier 4: Analysis Strategy (Runs for both scrape and analyze-only modes)
        analyzer = MarketAnalyzer()
        
        # Unpack both trends and outliers from the IQR filter
        trends, outliers = analyzer.calculate_trends(target_username=target_username, top_n=5)
        
        if not outliers.empty:
            print("\n================ VIRAL OUTLIERS (PINNED/ADS) ================")
            display_cols = [c for c in ['post_index', 'price', 'engagement'] if c in outliers.columns]
            print(outliers[display_cols].to_string(index=False))
            
        if not trends.empty:
            print("\n================ TOP ORGANIC TRENDING POSTS ================")
            display_cols = [c for c in ['post_index', 'price', 'engagement'] if c in trends.columns]
            print(trends[display_cols].to_string(index=False))
            
            print("\n================ AI BUSINESS INTELLIGENCE ================")
            
            # Loop through all the trending posts in the dataframe
            for index, post in trends.iterrows():
                post_id = post['post_index']
                print(f"\n[*] Analyzing comments for Trending Post (Index: {post_id})...")
                
                raw_comments = post.get('comments', '')
                
                # Skip the API call if the post has no comments
                if pd.isna(raw_comments) or not str(raw_comments).strip():
                    print("  -> No comments found to analyze.")
                    continue
                
                bi_data = analyzer.extract_business_intelligence(raw_comments)
                
                if "error" in bi_data:
                    print(f"  -> [!] NLP skipped: {bi_data['error']}")
                else:
                    print(json.dumps(bi_data, indent=2, ensure_ascii=False))
                    
            print("\n============================================================")
            
        elif outliers.empty:
            print("\n[!] No trend data could be calculated.")

    except FileNotFoundError as e:
        print(f"\n[!] {e}")
        print("[?] Make sure you have previously scraped this user before running in analyze-only mode.")
    except KeyboardInterrupt:
        print("\n[!] Pipeline interrupted by user.")
    except Exception as e:
        print(f"\n[!] Pipeline encountered a fatal error: {e}")
    finally:
        if raw_driver:
            print("[*] Closing browser session and cleaning up.")
            raw_driver.quit()
        sys.exit(0)

if __name__ == "__main__":
    main()