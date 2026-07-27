import os
import re
import json
import glob
import statistics
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

try:
    from groq import Groq
except ImportError:
    Groq = None


# ----------------------------------------------------------------------------
# Domain knowledge: product taxonomy for general e-commerce shops.
# Maps a canonical English label to the Persian keywords that identify it.
# The analyzer is generic, but this taxonomy dramatically sharpens the insights
# for each niche. Unknown products fall back to "Other".
# ----------------------------------------------------------------------------
PRODUCT_TAXONOMY = {
    # --- Jewelry (existing) ---
    "Bangle (النگو)":      ["النگو", "النگوی", "النگوطلاروس", "النگوآینه"],
    "Necklace (گردنبند)":  ["گردنبند"],
    "Bracelet (دستبند)":   ["دستبند"],
    "Ring (انگشتر)":       ["انگشتر"],
    "Full Set (سرویس)":    ["سرویس"],
    "Half Set (نیم‌ست)":   ["نیم‌ست", "نیمست", "نیم ست", "نیم‌ست", "نیمپوش", "تکپوش"],
    "Special Pack (پک)":   ["پک ویژه", "پک تخفیف", "فروش_ویژه"],

    # --- Clothes ---
    "Dress (پیراهن/آبی)": ["پیراهن", "آبی", "تونیک", "بلوز", "تی‌شرت", "تیشرت",
                           "پیش‌بند", "کتانی", "کت"],
    "Pants (شلوار)":       ["شلوار", "پانت", "باند", "جین", "جینز", "شلوارک",
                           "شلوار پارچه‌ای", "آفشان", "کاپری"],
    "Jacket/Coat (کت/مو)": ["کت", "مو", "ژاکت", "کاپشن", "بارانی", "ورزشی",
                           "بومبر", "پفی", "کاپشن پفی"],
    "Skirt (دامن)":        ["دامن", "مینی", "مکسی", "دامن بلند", "دامن کوتاه"],
    "Shirt (پیراهن مردانه)": ["پیراهن مردانه", "پیراهن", "شیرت", "تی‌شرت مردانه",
                             "پیراهن یقه‌دار", "پیراهن کارگو"],
    "Suit/Set (استرت)":    ["استرت", "دستیو", "دستیوه", "کت و شلوار", "پیش‌بند و شلوار"],

    # --- Accessories ---
    "Bag (کیف/کوله)":     ["کیف", "کیف دستی", "کیف شانه‌ای", "کوله", "کوله‌پشتی",
                           "بست", "کیف زن", "کیف مردانه", "کیف سفر"],
    "Hat (کلاه)":          ["کلاه", "کلاه نمدی", "کلاه بافت", "کلاه نقاب‌دار",
                           "بندانا", "شال", "واش", "هودی"],
    "Sunglasses (عینک آفتابی)": ["عینک آفتابی", "عینک آفتابی", "استیشن", "اوگلی",
                                "عینک طبی", "عینک خورشیدی"],
    "Scarf/Shawl (شال/روسری)": ["شال", "روسری", "بندانه", "شال ابریشمی",
                               "شال کشمیر", "روسری چرمی"],
    "Belt (کمربند)":       ["کمربند", "کمربند چرمی", "کمربند پارچه‌ای"],

    # --- Watches ---
    "Watch (ساعت)":        ["ساعت", "ساعت مچی", "ساعت دستی", "ساعت زنانه",
                           "ساعت مردانه", "ساعت هوشمند", "اسمارت‌واتچ", "ساعت مکانیکی"],

    # --- Perfume ---
    "Perfume (عطر/پارفوم)": ["عطر", "پارفوم", "عطر زنانه", "عطر مردانه",
                            "دستمال عطر", "اسپری بدن", "عطر گل", "عطر مینا",
                            "عطر ایرانی", "عطر فرانسوی", "عطر ترکی"],

    # --- Shoes ---
    "Shoes (کفش)":         ["کفش", "کفش زنانه", "کفش مردانه", "چکمه", "کتونی",
                           "کفش پاشنه‌بلند", "کفش ورزشی", "کتونی زنانه", "کتونی مردانه",
                           "صندل", "نیم‌بوت", "بوت", "کفش چرمی"],

    # --- Cosmetics & Skincare ---
    "Cosmetics (آرایش/مراقبت)": ["آرایش", "رژلب", "ریمل", "کرم", "مرطوب‌کننده",
                               "سرم", "ماسک", "ژل", "لوشن", "ضدآفتاب", "پرایمر",
                               "فاندیشن", "پودر", "بلاش", "ریمل", "سایه چشم",
                               "برش", "هایلایتر", "کنتور", "بازیابی", "مراقبت از پوست",
                               "ماسک صورت", "کرم شب", "کرم روز", "ضدچروز"],

    # --- Home & Living ---
    "Home Decor (دکوراسیون)": ["دکوراسیون", "پرتره", "قاب عکس", "شمعدان",
                              "روشنایی", "لوستر", "شمع", "گلدان", "پرگار",
                              "دکور خانه", "فرش", "سجاده", "پرده"],

    # --- Food & Health ---
    "Food & Health (سلامت/غذا)": ["سالم", "مکمل", "ویتامین", "پروتئین", "غذای سالم",
                                 "چای", "عسل", "گردو", "میوه خشک", "پروتئین",
                                 "کراتین", "بیوتین", "مغذی", "سوپلیمنت"],
}

# Buyer-intent signals used for a fast, offline (non-AI) first pass over comments.
PRICE_QUESTION_MARKERS = ["قیمت", "چند", "چنده", "چقدر", "قبمت", "قیمتش", "چقده"]
ORDER_INTENT_MARKERS = ["سفارش", "خرید", "بخرم", "میخوام", "می‌خوام", "بفرست", "ارسال", "موجوده", "موجود", "زنگ", "تماس", "شماره"]
COMPLAINT_MARKERS = ["گرون", "گران", "زیاده", "چرا نمیفرست", "نرسید", "خراب", "بد ", "افتضاح", "بی کیفیت", "بی‌کیفیت"]


class MarketAnalyzer:
    """
    Turns a single scraped profile CSV into a rich, structured `ProfileInsights`
    dictionary. Everything downstream (report, competitor comparison) consumes
    that dictionary, so all the "intelligence" lives here.
    """

    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        self.groq_client = Groq() if (Groq and os.environ.get("GROQ_API_KEY")) else None

    # ------------------------------------------------------------------ files
    def _get_latest_file(self, target_username: str) -> str:
        search_pattern = os.path.join(self.data_dir, f"{target_username}_*.csv")
        files = glob.glob(search_pattern)
        if not files:
            raise FileNotFoundError(f"No scraped data found for target: {target_username}")
        return max(files, key=os.path.getctime)

    # --------------------------------------------------------------- cleaning
    @staticmethod
    def _clean_price_series(raw) -> pd.Series:
        """
        The scraper's regex sometimes captures a truncated price (e.g. '6000'
        instead of '850000'). We keep the raw number but flag obviously broken
        values so they don't poison the statistics. A price under 1,000 Toman
        for most e-commerce categories is almost always a parsing artifact.
        """
        prices = pd.to_numeric(
            raw.astype(str).str.extract(r"(\d+)")[0], errors="coerce"
        )
        prices = prices.where(prices >= 1000, np.nan)
        return prices

    @staticmethod
    def _classify_product(text: str) -> str:
        if not isinstance(text, str):
            return "Other"
        for label, keywords in PRODUCT_TAXONOMY.items():
            for kw in keywords:
                if kw in text:
                    return label
        return "Other"

    @staticmethod
    def _extract_hashtags(text: str):
        if not isinstance(text, str):
            return []
        return re.findall(r"#([^\s#]+)", text)

    def _load_dataframe(self, target_username: str):
        file_path = self._get_latest_file(target_username)
        df = pd.read_csv(file_path)
        return df, file_path

    # ----------------------------------------------------- main entry point
    def analyze_profile(self, target_username: str, top_n: int = 5,
                        run_nlp: bool = True, nlp_post_limit: int = 6) -> dict:
        """
        Master method. Returns a fully populated insights dictionary for one
        profile. This is what both the report generator and the competitor
        comparison consume.
        """
        df, file_path = self._load_dataframe(target_username)
        print(f"[*] Analyzing latest data from: {os.path.basename(file_path)}")

        insights = {
            "username": target_username,
            "source_file": os.path.basename(file_path),
            "post_count": 0,
            "has_data": False,
        }

        if df.empty:
            print("[!] The data file is empty.")
            return insights

        # --- Normalize columns -------------------------------------------------
        df["price_clean"] = self._clean_price_series(df.get("price", pd.Series(dtype=str)))

        if "engagement" in df.columns:
            df["engagement"] = pd.to_numeric(df["engagement"], errors="coerce").fillna(0)
        else:
            likes = pd.to_numeric(df["likes"], errors="coerce").fillna(0) if "likes" in df.columns else 0
            comments = pd.to_numeric(df["comments"], errors="coerce").fillna(0) if "comments" in df.columns else 0
            df["engagement"] = likes + comments

        if "description" not in df.columns:
            df["description"] = ""
        if "comments" not in df.columns:
            df["comments"] = ""
        df["description"] = df["description"].fillna("")
        df["comments"] = df["comments"].fillna("")

        df["category"] = df["description"].apply(self._classify_product)
        df["comment_count"] = df["comments"].apply(
            lambda c: 0 if not str(c).strip() else len([l for l in str(c).split("\n") if l.strip()])
        )

        insights["post_count"] = len(df)
        insights["has_data"] = True

        # --- Engagement statistics --------------------------------------------
        insights["engagement"] = self._engagement_stats(df)

        # --- Outliers & organic trends ----------------------------------------
        trending_df, outliers_df, standard_df = self._split_trends(df, top_n)
        insights["top_posts"] = self._posts_to_records(trending_df)
        insights["viral_outliers"] = self._posts_to_records(outliers_df)

        # --- Pricing intelligence ---------------------------------------------
        insights["pricing"] = self._pricing_stats(df)

        # --- Category / product-mix intelligence ------------------------------
        insights["categories"] = self._category_stats(df)

        # --- Hashtag intelligence ---------------------------------------------
        insights["hashtags"] = self._hashtag_stats(df, top=12)

        # --- Momentum (does newer content perform better?) --------------------
        insights["momentum"] = self._momentum_stats(df)

        # --- Fast offline comment signals (no API cost) -----------------------
        insights["demand_signals"] = self._offline_comment_signals(df)

        # --- Deep AI business intelligence on the best posts ------------------
        insights["ai_bi"] = {}
        if run_nlp and self.groq_client:
            nlp_targets = trending_df.head(nlp_post_limit)
            for _, post in nlp_targets.iterrows():
                raw_comments = post.get("comments", "")
                if pd.isna(raw_comments) or not str(raw_comments).strip():
                    continue
                post_id = int(post["post_index"])
                print(f"[*] AI analysis of comments on post #{post_id}...")
                insights["ai_bi"][post_id] = self.extract_business_intelligence(raw_comments)
        elif run_nlp and not self.groq_client:
            insights["ai_bi_note"] = "GROQ_API_KEY not set - AI comment analysis skipped."

        # --- Aggregate AI intelligence across posts ---------------------------
        insights["ai_summary"] = self._aggregate_ai(insights["ai_bi"])

        # keep the cleaned frame around for chart generation
        insights["_dataframe"] = df

        return insights

    # ------------------------------------------------------------ stat blocks
    def _engagement_stats(self, df: pd.DataFrame) -> dict:
        eng = df["engagement"]
        return {
            "total": int(eng.sum()),
            "mean": float(eng.mean()),
            "median": float(eng.median()),
            "max": int(eng.max()),
            "min": int(eng.min()),
            "std": float(eng.std(ddof=0)) if len(eng) > 1 else 0.0,
        }

    def _split_trends(self, df: pd.DataFrame, top_n: int):
        eng = df["engagement"]
        q1, q3 = eng.quantile(0.25), eng.quantile(0.75)
        upper = q3 + 1.5 * (q3 - q1)
        outliers = df[df["engagement"] > upper].sort_values("engagement", ascending=False)
        standard = df[df["engagement"] <= upper]
        trending = standard.sort_values("engagement", ascending=False).head(top_n)
        return trending, outliers, standard

    def _posts_to_records(self, sub: pd.DataFrame):
        records = []
        for _, row in sub.iterrows():
            price = row.get("price_clean")
            records.append({
                "post_index": int(row["post_index"]),
                "category": row.get("category", "Other"),
                "price": None if pd.isna(price) else int(price),
                "engagement": int(row["engagement"]),
                "comment_count": int(row.get("comment_count", 0)),
                "snippet": self._first_line(row.get("description", "")),
            })
        return records

    @staticmethod
    def _first_line(text: str, max_len: int = 60) -> str:
        if not isinstance(text, str):
            return ""
        first = next((l.strip() for l in text.split("\n") if l.strip()), "")
        return first[:max_len]

    def _pricing_stats(self, df: pd.DataFrame) -> dict:
        prices = df["price_clean"].dropna()
        if prices.empty:
            return {"available": False}

        # Engagement-weighted average price reveals the price point buyers
        # actually respond to (not just what the shop posts).
        priced = df.dropna(subset=["price_clean"])
        weight = priced["engagement"].clip(lower=1)
        weighted_avg = float((priced["price_clean"] * weight).sum() / weight.sum())

        # Which price band gets the most love?
        bands = self._price_bands(priced)

        return {
            "available": True,
            "count_priced": int(prices.count()),
            "count_unpriced": int(df["price_clean"].isna().sum()),
            "min": int(prices.min()),
            "max": int(prices.max()),
            "mean": float(prices.mean()),
            "median": float(prices.median()),
            "engagement_weighted_avg": weighted_avg,
            "best_selling_band": bands["best_band"],
            "bands": bands["bands"],
        }

    def _price_bands(self, priced: pd.DataFrame) -> dict:
        edges = [0, 500_000, 1_000_000, 2_000_000, 4_000_000, float("inf")]
        labels = ["<500K", "500K-1M", "1M-2M", "2M-4M", "4M+"]
        bands = []
        best_band, best_eng = None, -1
        for i in range(len(labels)):
            lo, hi = edges[i], edges[i + 1]
            mask = (priced["price_clean"] >= lo) & (priced["price_clean"] < hi)
            subset = priced[mask]
            if subset.empty:
                bands.append({"label": labels[i], "posts": 0, "avg_engagement": 0.0})
                continue
            avg_eng = float(subset["engagement"].mean())
            bands.append({
                "label": labels[i],
                "posts": int(len(subset)),
                "avg_engagement": avg_eng,
            })
            if avg_eng > best_eng:
                best_eng, best_band = avg_eng, labels[i]
        return {"bands": bands, "best_band": best_band}

    def _category_stats(self, df: pd.DataFrame) -> dict:
        rows = []
        for cat, sub in df.groupby("category"):
            priced = sub["price_clean"].dropna()
            rows.append({
                "category": cat,
                "posts": int(len(sub)),
                "share_pct": round(100 * len(sub) / len(df), 1),
                "avg_engagement": float(sub["engagement"].mean()),
                "total_engagement": int(sub["engagement"].sum()),
                "avg_price": float(priced.mean()) if not priced.empty else None,
            })
        rows.sort(key=lambda r: r["total_engagement"], reverse=True)

        # Identify the best & worst performing category by average engagement
        by_avg = sorted(rows, key=lambda r: r["avg_engagement"], reverse=True)
        return {
            "breakdown": rows,
            "star_category": by_avg[0]["category"] if by_avg else None,
            "underperformer": by_avg[-1]["category"] if len(by_avg) > 1 else None,
        }

    def _hashtag_stats(self, df: pd.DataFrame, top: int = 12) -> dict:
        tag_counter = Counter()
        tag_engagement = defaultdict(list)
        for _, row in df.iterrows():
            tags = self._extract_hashtags(row["description"])
            for t in set(tags):  # count each tag once per post
                tag_counter[t] += 1
                tag_engagement[t].append(row["engagement"])

        most_used = [{"tag": t, "count": c} for t, c in tag_counter.most_common(top)]

        # Highest-performing tags (min 2 uses to be meaningful)
        perf = []
        for t, engs in tag_engagement.items():
            if len(engs) >= 2:
                perf.append({"tag": t, "uses": len(engs), "avg_engagement": float(np.mean(engs))})
        perf.sort(key=lambda x: x["avg_engagement"], reverse=True)

        return {"most_used": most_used, "top_performing": perf[:top]}

    def _momentum_stats(self, df: pd.DataFrame) -> dict:
        """
        post_index increases with time (1 = oldest scraped). Comparing the
        first vs. last third of posts tells us whether the page is growing.
        """
        if len(df) < 6:
            return {"available": False}
        ordered = df.sort_values("post_index")
        third = max(1, len(ordered) // 3)
        early = ordered.head(third)["engagement"].mean()
        recent = ordered.tail(third)["engagement"].mean()
        growth = None
        if early > 0:
            growth = round(100 * (recent - early) / early, 1)
        return {
            "available": True,
            "early_avg_engagement": float(early),
            "recent_avg_engagement": float(recent),
            "growth_pct": growth,
            "trend": "growing" if growth and growth > 10 else
                     "declining" if growth and growth < -10 else "stable",
        }

    def _offline_comment_signals(self, df: pd.DataFrame) -> dict:
        """
        A zero-cost first pass across ALL comments (not just top posts) using
        keyword heuristics. Catches demand the AI pass (limited to top posts)
        would miss, and works even without an API key.
        """
        price_questions = 0
        order_intents = 0
        complaints = 0
        total_comments = 0
        hot_posts = []  # posts with many buyer questions

        for _, row in df.iterrows():
            comments = str(row.get("comments", ""))
            if not comments.strip():
                continue
            lines = [l for l in comments.split("\n") if l.strip()]
            post_questions = 0
            for line in lines:
                total_comments += 1
                text = line.split(":", 1)[-1] if ":" in line else line
                if any(m in text for m in PRICE_QUESTION_MARKERS):
                    price_questions += 1
                    post_questions += 1
                if any(m in text for m in ORDER_INTENT_MARKERS):
                    order_intents += 1
                if any(m in text for m in COMPLAINT_MARKERS):
                    complaints += 1
            if post_questions >= 1:
                hot_posts.append({
                    "post_index": int(row["post_index"]),
                    "questions": post_questions,
                    "snippet": self._first_line(row.get("description", "")),
                })

        hot_posts.sort(key=lambda p: p["questions"], reverse=True)
        return {
            "total_comments_scanned": total_comments,
            "price_questions": price_questions,
            "order_intents": order_intents,
            "complaints": complaints,
            "posts_with_buyer_questions": hot_posts[:8],
        }

    # ------------------------------------------------------------ AI section
    def _format_comments_for_nlp(self, raw_comments):
        if pd.isna(raw_comments) or not str(raw_comments).strip():
            return "[]"
        formatted = []
        for line in str(raw_comments).split("\n"):
            if ":" in line:
                username, text = line.split(":", 1)
                formatted.append({"username": username.strip(), "text": text.strip()})
            else:
                formatted.append({"username": "anonymous", "text": line.strip()})
        return json.dumps(formatted, ensure_ascii=False)

    def extract_business_intelligence(self, raw_comments):
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
3. "price_resistance_count": The number of comments explicitly complaining that the price is too high.
4. "objections": Questions or concerns causing buying friction (e.g., shipping times, material quality, trust issues).
5. "sentiment": Overall comment sentiment, one of "positive", "neutral", or "negative".

You MUST respond ONLY with a valid JSON object matching this exact schema. Do not include markdown formatting like ```json or any conversational text.

{
  "leads": [{"username": "string", "intent": "string"}],
  "inventory_gaps": ["string"],
  "price_resistance_count": 0,
  "objections": ["string"],
  "sentiment": "positive"
}"""

        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": json_comments},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            return json.loads(response.choices[0].message.content or "{}")
        except Exception as e:

            return {"error": f"API request failed: {str(e)}"}

    def _aggregate_ai(self, ai_bi: dict) -> dict:
        """Roll up per-post AI results into shop-wide totals for the summary."""
        all_leads, all_gaps, all_objections = [], [], []
        price_resistance = 0
        sentiments = Counter()
        for post_id, bi in ai_bi.items():
            if not isinstance(bi, dict) or "error" in bi:
                continue
            for lead in bi.get("leads", []):
                all_leads.append({"post": post_id, **lead})
            all_gaps.extend(bi.get("inventory_gaps", []))
            all_objections.extend(bi.get("objections", []))
            price_resistance += int(bi.get("price_resistance_count", 0) or 0)
            sent = bi.get("sentiment")
            if sent:
                sentiments[sent] += 1

        # Rank most-requested inventory gaps
        gap_counter = Counter(g.strip() for g in all_gaps if g and g.strip())
        obj_counter = Counter(o.strip() for o in all_objections if o and o.strip())

        return {
            "total_leads": len(all_leads),
            "leads": all_leads,
            "top_inventory_gaps": gap_counter.most_common(10),
            "top_objections": obj_counter.most_common(10),
            "price_resistance_total": price_resistance,
            "sentiment_breakdown": dict(sentiments),
        }

    # ------------------------------------------------ backward-compat shim
    def calculate_trends(self, target_username: str, top_n=5):
        """Kept so any old callers still work; returns (trending, outliers)."""
        df, _ = self._load_dataframe(target_username)
        df["price_clean"] = self._clean_price_series(df.get("price", pd.Series(dtype=str)))
        if "engagement" not in df.columns:
            df["engagement"] = 0
        df["engagement"] = pd.to_numeric(df["engagement"], errors="coerce").fillna(0)
        trending, outliers, _ = self._split_trends(df, top_n)
        return trending, outliers


# ----------------------------------------------------------------------------
# Competitor comparison: consumes two (or more) ProfileInsights dicts and
# produces a head-to-head analysis plus actionable, sellable advice.
# ----------------------------------------------------------------------------
class CompetitorComparator:
    def compare(self, client: dict, competitors: list) -> dict:
        comp = [c for c in competitors if c.get("has_data")]
        result = {
            "client": client["username"],
            "competitors": [c["username"] for c in comp],
            "metrics": self._metric_table(client, comp),
            "positioning": self._positioning(client, comp),
            "advice": self._advice(client, comp),
        }
        return result

    def _metric_table(self, client, comp):
        def row(p):
            return {
                "username": p["username"],
                "posts": p["post_count"],
                "avg_engagement": round(p["engagement"]["mean"], 1) if p.get("engagement") else 0,
                "median_engagement": round(p["engagement"]["median"], 1) if p.get("engagement") else 0,
                "total_engagement": p["engagement"]["total"] if p.get("engagement") else 0,
                "avg_price": round(p["pricing"]["mean"]) if p.get("pricing", {}).get("available") else None,
                "star_category": p.get("categories", {}).get("star_category"),
                "trend": p.get("momentum", {}).get("trend", "n/a"),
            }
        return {"client": row(client), "competitors": [row(c) for c in comp]}

    def _positioning(self, client, comp):
        """Where does the client stand relative to the competitive set?"""
        if not comp:
            return {}
        c_eng = client["engagement"]["mean"]
        comp_eng = [c["engagement"]["mean"] for c in comp]
        avg_comp_eng = statistics.mean(comp_eng)

        c_price = client["pricing"]["mean"] if client["pricing"].get("available") else None
        comp_prices = [c["pricing"]["mean"] for c in comp if c["pricing"].get("available")]
        avg_comp_price = statistics.mean(comp_prices) if comp_prices else None

        pos = {
            "engagement_vs_market_pct": round(100 * (c_eng - avg_comp_eng) / avg_comp_eng, 1)
            if avg_comp_eng else None,
            "engagement_rank": 1 + sum(1 for e in comp_eng if e > c_eng),
            "field_size": len(comp) + 1,
        }
        if c_price and avg_comp_price:
            pos["price_vs_market_pct"] = round(100 * (c_price - avg_comp_price) / avg_comp_price, 1)
            pos["price_position"] = (
                "premium" if c_price > avg_comp_price * 1.1 else
                "budget" if c_price < avg_comp_price * 0.9 else "mid-market"
            )
        return pos

    def _advice(self, client, comp):
        """
        The money section. Generates concrete, human-readable recommendations
        the client can act on — this is what makes the report sellable.
        """
        advice = []
        if not comp:
            return advice

        comp_eng = [c["engagement"]["mean"] for c in comp]
        avg_comp_eng = statistics.mean(comp_eng)
        c_eng = client["engagement"]["mean"]

        # 1. Engagement gap
        if c_eng < avg_comp_eng * 0.9:
            gap = round(100 * (avg_comp_eng - c_eng) / avg_comp_eng, 1)
            advice.append(
                f"Your average engagement is {gap}% below the competitor average. "
                f"Increase posting of your strongest category and study competitors' top posts for content ideas."
            )
        elif c_eng > avg_comp_eng * 1.1:
            lead = round(100 * (c_eng - avg_comp_eng) / avg_comp_eng, 1)
            advice.append(
                f"You lead the competitive set on engagement by {lead}%. "
                f"Leverage this authority by increasing post frequency and introducing higher-margin products."
            )

        # 2. Category opportunity: a category competitors win that the client under-serves
        client_cats = {c["category"]: c for c in client.get("categories", {}).get("breakdown", [])}
        comp_star_cats = Counter()
        for c in comp:
            star = c.get("categories", {}).get("star_category")
            if star:
                comp_star_cats[star] += 1
        for cat, votes in comp_star_cats.most_common():
            client_cat = client_cats.get(cat)
            if not client_cat or client_cat["share_pct"] < 10:
                advice.append(
                    f"Competitors are winning with '{cat}', but it's under-represented in your feed "
                    f"({client_cat['share_pct'] if client_cat else 0}% of posts). Test more content in this category."
                )
                break

        # 3. Pricing advice
        if client["pricing"].get("available"):
            comp_prices = [c["pricing"]["mean"] for c in comp if c["pricing"].get("available")]
            if comp_prices:
                avg_comp_price = statistics.mean(comp_prices)
                c_price = client["pricing"]["mean"]
                best_band = client["pricing"].get("best_selling_band")
                if c_price > avg_comp_price * 1.15:
                    advice.append(
                        f"Your average price is {round(100*(c_price-avg_comp_price)/avg_comp_price)}% above the market. "
                        f"Consider entry-level products to capture price-sensitive buyers (your best-responding band is {best_band})."
                    )
                elif c_price < avg_comp_price * 0.85:
                    advice.append(
                        f"You are priced {round(100*(avg_comp_price-c_price)/avg_comp_price)}% below the market — "
                        f"there is room to raise prices or introduce a premium line without losing competitiveness."
                    )

        # 4. Momentum advice
        trend = client.get("momentum", {}).get("trend")
        if trend == "declining":
            advice.append(
                "Your recent posts are under-performing older ones — engagement momentum is declining. "
                "Refresh your content format and reactivate your most engaged commenters."
            )
        elif trend == "growing":
            advice.append(
                "Your engagement momentum is positive — recent posts outperform older ones. "
                "Now is the ideal time to launch promotions while reach is expanding."
            )

        # 5. Demand-capture advice from unanswered buyer questions
        signals = client.get("demand_signals", {})
        if signals.get("price_questions", 0) > 0:
            advice.append(
                f"{signals['price_questions']} comments asked about price directly. "
                f"Publishing prices clearly in captions and replying fast will convert these warm leads."
            )

        # 6. Inventory gap advice from AI
        gaps = client.get("ai_summary", {}).get("top_inventory_gaps", [])
        if gaps:
            top_gap = gaps[0][0]
            advice.append(
                f"Customers are actively requesting variations not currently offered (e.g. '{top_gap}'). "
                f"Stocking these is a low-risk, demand-validated inventory decision."
            )

        return advice
