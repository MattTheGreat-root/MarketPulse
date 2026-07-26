import os
import pandas as pd
import glob

class MarketAnalyzer:
    def __init__(self, data_dir="data"):
        self.data_dir = data_dir

    def _get_latest_file(self, target_username: str) -> str:
        """
        Finds the most recently created CSV file for a given target.
        """
        search_pattern = os.path.join(self.data_dir, f"{target_username}_*.csv")
        files = glob.glob(search_pattern)
        if not files:
            raise FileNotFoundError(f"No scraped data found for target: {target_username}")
        # Sort files by creation time
        return max(files, key=os.path.getctime)

    def calculate_trends(self, target_username: str, top_n=5):
        file_path = self._get_latest_file(target_username)
        print(f"[*] Analyzing latest data from: {os.path.basename(file_path)}")

        df = pd.read_csv(file_path)

        if df.empty:
            print("[!] The data file is empty.")
            return pd.DataFrame()

        # BULLETPROOF PRICE CLEANING:
        # Convert to string, extract only digits, convert to float.
        # If no digits are found (or it was 'None'), it safely becomes NaN.
        df['price'] = df['price'].astype(str).str.extract(r'(\d+)')[0].astype(float)

        # The scraper now stores a single combined `engagement` column
        # (likes + comments). Fall back gracefully if it is missing.
        if 'engagement' in df.columns:
            df['engagement'] = pd.to_numeric(df['engagement'], errors='coerce').fillna(0)
        else:
            likes = pd.to_numeric(df['likes'], errors='coerce').fillna(0) if 'likes' in df.columns else 0
            comments = pd.to_numeric(df['comments'], errors='coerce').fillna(0) if 'comments' in df.columns else 0
            df['engagement'] = likes + comments


        trending_df = df.sort_values(by='engagement', ascending=False).head(top_n)

        return trending_df

