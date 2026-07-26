import os
import json
import pandas as pd
import glob
from groq import Groq

class MarketAnalyzer:
    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        # Automatically detects the GROQ_API_KEY environment variable
        self.groq_client = Groq() if os.environ.get("GROQ_API_KEY") else None

    def _get_latest_file(self, target_username: str) -> str:
        search_pattern = os.path.join(self.data_dir, f"{target_username}_*.csv")
        files = glob.glob(search_pattern)
        if not files:
            raise FileNotFoundError(f"No scraped data found for target: {target_username}")
        return max(files, key=os.path.getctime)

    def calculate_trends(self, target_username: str, top_n=5):
        file_path = self._get_latest_file(target_username)
        print(f"[*] Analyzing latest data from: {os.path.basename(file_path)}")

        df = pd.read_csv(file_path)

        if df.empty:
            print("[!] The data file is empty.")
            return pd.DataFrame(), pd.DataFrame()

        # 1. BULLETPROOF PRICE CLEANING
        df['price'] = df['price'].astype(str).str.extract(r'(\d+)')[0].astype(float)
        df.dropna(subset=['price'], inplace=True)

        if df.empty:
            print("[!] No valid data remaining after price filtering.")
            return pd.DataFrame(), pd.DataFrame()

        # 2. ENGAGEMENT STANDARDIZATION
        if 'engagement' in df.columns:
            df['engagement'] = pd.to_numeric(df['engagement'], errors='coerce').fillna(0)
        else:
            likes = pd.to_numeric(df['likes'], errors='coerce').fillna(0) if 'likes' in df.columns else 0
            comments = pd.to_numeric(df['comments'], errors='coerce').fillna(0) if 'comments' in df.columns else 0
            df['engagement'] = likes + comments

        # 3. OUTLIER DETECTION (IQR Method)
        Q1 = df['engagement'].quantile(0.25)
        Q3 = df['engagement'].quantile(0.75)
        IQR = Q3 - Q1
        upper_bound = Q3 + 1.5 * IQR

        outliers_df = df[df['engagement'] > upper_bound].sort_values(by='engagement', ascending=False)
        standard_df = df[df['engagement'] <= upper_bound]

        # 4. TREND IDENTIFICATION
        trending_df = standard_df.sort_values(by='engagement', ascending=False).head(top_n)

        return trending_df, outliers_df

    def _format_comments_for_nlp(self, raw_comments):
        """Converts the newline-separated text back into a JSON array of dicts for the prompt."""
        if pd.isna(raw_comments) or not str(raw_comments).strip():
            return "[]"
        
        formatted = []
        for line in str(raw_comments).split('\n'):
            if ':' in line:
                username, text = line.split(':', 1)
                formatted.append({"username": username.strip(), "text": text.strip()})
            else:
                formatted.append({"username": "anonymous", "text": line.strip()})
                
        return json.dumps(formatted, ensure_ascii=False)

    def extract_business_intelligence(self, raw_comments):
        """Sends the formatted comments to Groq and returns a parsed JSON dictionary."""
        if not self.groq_client:
            return {"error": "GROQ_API_KEY environment variable is not set."}

        json_comments = self._format_comments_for_nlp(raw_comments)
        
        if json_comments == "[]":
            return {"error": "No comments to analyze for this post."}

        sys_prompt = """You are a highly accurate e-commerce data extraction engine. Your task is to analyze a list of social media comments from a product post and extract business intelligence. 

The comments will be provided as a JSON array of objects: [{"username": "...", "text": "..."}].
The comments may be in Persian/Farsi. You must analyze the meaning in the original language, but your final output MUST be in English.

Extract the following intelligence:
1. "leads": Users showing high purchase intent (asking for price, availability, or how to order).
2. "inventory_gaps": Specific variations requested by users (colors, sizes, models) that imply demand.
3. "price_resistance": The number of comments explicitly complaining that the price is too high.
4. "objections": Questions or concerns causing buying friction (e.g., shipping times, material quality, trust issues).

You MUST respond ONLY with a valid JSON object matching this exact schema. Do not include markdown formatting like ```json or any conversational text.

{
  "leads": [
    {
      "username": "string",
      "intent": "string (brief summary of what they want)"
    }
  ],
  "inventory_gaps": ["string", "string"],
  "price_resistance_count": 0,
  "objections": ["string", "string"]
}"""

        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile", # Highly capable logic model
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": json_comments}
                ],
                # Force the API to drop conversational text and strictly return JSON
                response_format={"type": "json_object"},
                temperature=0.0
            )
            
            return json.loads(response.choices[0].message.content)
            
        except Exception as e:
            return {"error": f"API request failed: {str(e)}"}