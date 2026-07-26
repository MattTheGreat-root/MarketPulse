import os
import html
from datetime import datetime
from pathlib import Path

from weasyprint import HTML

from core import charts

# Absolute path to the bundled Vazirmatn fonts so WeasyPrint can embed them
# in the PDF regardless of the current working directory.
_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def _font_face_css():
    reg = (_FONT_DIR / "Vazirmatn-Regular.ttf").as_uri()
    bold = (_FONT_DIR / "Vazirmatn-Bold.ttf").as_uri()
    return f"""
    @font-face {{
        font-family: 'Vazirmatn';
        src: url('{reg}') format('truetype');
        font-weight: normal; font-style: normal;
    }}
    @font-face {{
        font-family: 'Vazirmatn';
        src: url('{bold}') format('truetype');
        font-weight: bold; font-style: normal;
    }}
    """



def _fmt_price(value):
    if value is None:
        return "نامشخص"
    try:
        return f"{int(value):,} تومان"
    except (TypeError, ValueError):
        return "نامشخص"


def _fmt_num(value):
    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return str(value)


def _e(text):
    return html.escape(str(text))


# Persian labels for momentum trend
TREND_FA = {
    "growing": "📈 در حال رشد",
    "declining": "📉 در حال افت",
    "stable": "➖ ثابت",
    "n/a": "نامشخص",
}

# Map bilingual product category labels (e.g. "Bangle (النگو)") to their
# English part so SVG chart labels shape/render correctly in WeasyPrint.
def _cat_en(label):
    if not label:
        return label
    s = str(label)
    if "(" in s:
        s = s.split("(", 1)[0].strip()
    return s or str(label)



class ReportGenerator:
    """
    Generates a polished, client-ready Persian report (HTML + PDF) from the
    structured insights produced by MarketAnalyzer. Supports a single client
    profile plus optional competitor comparison.
    """

    def __init__(self, output_dir="reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    # ================================================================= public
    def generate_report(self, client_insights: dict, comparison: dict | None = None,
                         competitor_insights: list | None = None,
                         make_pdf: bool = True, brand: str = "MarketPulse"):
        username = client_insights["username"]
        competitor_insights = competitor_insights or []

        body = self._build_body(client_insights, comparison, competitor_insights, brand)
        styled_html = self._wrap_html(body, username, brand)

        html_path = os.path.join(self.output_dir, f"{username}_market_report.html")
        with open(html_path, "w", encoding="utf-8-sig") as f:
            f.write(styled_html)
        print(f"[+] HTML report generated at: {html_path}")

        pdf_path = None
        if make_pdf:
            pdf_path = os.path.join(self.output_dir, f"{username}_market_report.pdf")
            # Remove any stale PDF first so the packager never ships an old one.
            if os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except OSError:
                    pass
            try:
                HTML(string=styled_html).write_pdf(pdf_path)

                print(f"[+] PDF report generated at: {pdf_path}")
            except Exception as e:
                print(f"[!] PDF generation failed: {e}")
                print(f"[+] Fallback: open the HTML in Chrome and Ctrl+P to save as PDF.")
                pdf_path = None

        return {"html": html_path, "pdf": pdf_path}

    # ============================================================ body builder
    def _build_body(self, client, comparison, competitors, brand):
        sections = [
            self._cover(client, brand),
            self._executive_summary(client, comparison),
            self._kpi_cards(client),
            self._engagement_section(client),
            self._category_section(client),
            self._pricing_section(client),
            self._hashtag_section(client),
            self._demand_section(client),
            self._ai_section(client),
        ]
        if comparison and competitors:
            sections.append(self._competitor_section(client, comparison, competitors))
            sections.append(self._advice_section(comparison))
        sections.append(self._top_posts_section(client))
        sections.append(self._footer(brand))
        return "\n".join(s for s in sections if s)

    # -------------------------------------------------------------- cover page
    def _cover(self, client, brand):
        date_str = datetime.now().strftime("%Y-%m-%d")
        return f"""
        <section class="cover">
            <div class="cover-badge">{_e(brand)}</div>
            <h1 class="cover-title">گزارش تحلیل بازار و هوش تجاری</h1>
            <div class="cover-sub">تحلیل جامع عملکرد، رفتار مشتری و جایگاه رقابتی</div>
            <div class="cover-target">پیج مورد بررسی: <span>@{_e(client['username'])}</span></div>
            <div class="cover-meta">
                <span>تاریخ گزارش: {date_str}</span>
                <span>تعداد پست تحلیل‌شده: {client.get('post_count', 0)}</span>
            </div>
        </section>
        """

    # ------------------------------------------------------ executive summary
    def _executive_summary(self, client, comparison):
        eng = client.get("engagement", {})
        cats = client.get("categories", {})
        momentum = client.get("momentum", {})
        pricing = client.get("pricing", {})

        bullets = []
        star = cats.get("star_category")
        if star:
            bullets.append(f"محبوب‌ترین دسته محصول از نظر تعامل: <b>{_e(star)}</b>")
        if momentum.get("available") and momentum.get("growth_pct") is not None:
            g = momentum["growth_pct"]
            direction = "رشد" if g >= 0 else "افت"
            bullets.append(f"روند تعامل پیج: <b>{TREND_FA.get(momentum['trend'])}</b> "
                           f"({direction} {abs(g)}٪ نسبت به پست‌های قدیمی‌تر)")
        if pricing.get("available"):
            bullets.append(f"بهترین بازه قیمتی از نظر جذب تعامل: <b>{_e(pricing.get('best_selling_band'))} تومان</b>")
        if eng:
            bullets.append(f"میانگین تعامل هر پست: <b>{_fmt_num(eng.get('mean'))}</b>")
        signals = client.get("demand_signals", {})
        if signals.get("price_questions"):
            bullets.append(f"تعداد کامنت‌های پرسش قیمت (لید بالقوه): <b>{signals['price_questions']}</b>")
        if comparison and comparison.get("positioning", {}).get("engagement_rank"):
            pos = comparison["positioning"]
            bullets.append(f"رتبه پیج شما در بین رقبا از نظر تعامل: "
                           f"<b>{pos['engagement_rank']} از {pos['field_size']}</b>")

        items = "".join(f"<li>{b}</li>" for b in bullets)
        return f"""
        <section class="section">
            <h2>۱. خلاصه مدیریتی</h2>
            <div class="callout">
                <p>این بخش مهم‌ترین یافته‌های گزارش را به صورت خلاصه ارائه می‌دهد تا در یک نگاه تصمیم‌گیری کنید.</p>
                <ul class="summary-list">{items}</ul>
            </div>
        </section>
        """

    # ------------------------------------------------------------- KPI cards
    def _kpi_cards(self, client):
        eng = client.get("engagement", {})
        pricing = client.get("pricing", {})
        signals = client.get("demand_signals", {})
        ai = client.get("ai_summary", {})

        cards = [
            ("کل تعامل", _fmt_num(eng.get("total", 0)), "مجموع لایک و کامنت"),
            ("میانگین تعامل", _fmt_num(eng.get("mean", 0)), "به ازای هر پست"),
            ("پربازدیدترین پست", _fmt_num(eng.get("max", 0)), "بالاترین تعامل"),
            ("لیدهای شناسایی‌شده", _fmt_num(ai.get("total_leads", 0)), "مشتری آماده خرید"),
            ("پرسش قیمت", _fmt_num(signals.get("price_questions", 0)), "در کل کامنت‌ها"),
            ("میانگین قیمت", _fmt_price(pricing.get("mean")) if pricing.get("available") else "—", "محصولات دارای قیمت"),
        ]
        card_html = "".join(
            f'<div class="kpi"><div class="kpi-val">{_e(v)}</div>'
            f'<div class="kpi-title">{_e(t)}</div>'
            f'<div class="kpi-note">{_e(n)}</div></div>'
            for t, v, n in cards
        )
        return f"""
        <section class="section">
            <h2>۲. شاخص‌های کلیدی عملکرد</h2>
            <div class="kpi-grid">{card_html}</div>
        </section>
        """

    # -------------------------------------------------------- engagement chart
    def _engagement_section(self, client):
        df = client.get("_dataframe")
        chart = ""
        if df is not None and len(df) >= 2:
            ordered = df.sort_values("post_index")
            points = [(f"#{int(r['post_index'])}", r["engagement"]) for _, r in ordered.iterrows()]
            chart = charts.line_chart(points, title="Engagement Trend (Oldest -> Newest)")


        momentum = client.get("momentum", {})
        note = ""
        if momentum.get("available"):
            early = _fmt_num(momentum["early_avg_engagement"])
            recent = _fmt_num(momentum["recent_avg_engagement"])
            trend = TREND_FA.get(momentum["trend"])
            note = (f"<p>میانگین تعامل پست‌های ابتدایی: <b>{early}</b> — "
                    f"پست‌های اخیر: <b>{recent}</b>. وضعیت روند: <b>{trend}</b></p>")
        return f"""
        <section class="section">
            <h2>۳. روند تعامل و شتاب رشد</h2>
            <div class="chart-box">{chart}</div>
            {note}
        </section>
        """

    # ---------------------------------------------------------- category chart
    def _category_section(self, client):
        cats = client.get("categories", {})
        breakdown = cats.get("breakdown", [])
        if not breakdown:
            return ""

        share_data = [(_cat_en(c["category"]), c["posts"]) for c in breakdown]
        eng_data = sorted(
            [(_cat_en(c["category"]), c["avg_engagement"]) for c in breakdown],
            key=lambda x: x[1], reverse=True
        )

        donut = charts.donut_chart(share_data, title="Post Share by Category")
        bars = charts.bar_chart(eng_data, title="Avg Engagement by Category")


        rows = ""
        for c in breakdown:
            price = _fmt_price(c["avg_price"]) if c.get("avg_price") else "—"
            rows += (f"<tr><td>{_e(c['category'])}</td><td>{c['posts']}</td>"
                     f"<td>{c['share_pct']}٪</td><td>{_fmt_num(c['avg_engagement'])}</td>"
                     f"<td>{price}</td></tr>")

        star = cats.get("star_category")
        under = cats.get("underperformer")
        insight = ""
        if star and under and star != under:
            insight = (f"<div class='insight'>💡 دسته <b>{_e(star)}</b> بیشترین تعامل را جذب می‌کند و "
                       f"دسته <b>{_e(under)}</b> کمترین. پیشنهاد می‌شود محتوای بیشتری در دسته پرطرفدار تولید شود.</div>")

        return f"""
        <section class="section">
            <h2>۴. تحلیل سبد محصولات</h2>
            <div class="two-col">
                <div class="chart-box">{donut}</div>
                <div class="chart-box">{bars}</div>
            </div>
            <table class="data-table">
                <thead><tr><th>دسته</th><th>تعداد پست</th><th>سهم</th><th>میانگین تعامل</th><th>میانگین قیمت</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
            {insight}
        </section>
        """

    # ----------------------------------------------------------- pricing chart
    def _pricing_section(self, client):
        pricing = client.get("pricing", {})
        if not pricing.get("available"):
            return """
            <section class="section">
                <h2>۵. تحلیل قیمت‌گذاری</h2>
                <p>داده قیمت کافی برای تحلیل موجود نبود.</p>
            </section>
            """
        bands = pricing.get("bands", [])
        band_data = [(b["label"], b["avg_engagement"]) for b in bands if b["posts"] > 0]
        chart = charts.bar_chart(band_data, title="Avg Engagement by Price Band (Toman)")


        best = pricing.get("best_selling_band")
        weighted = _fmt_price(pricing.get("engagement_weighted_avg"))
        insight = (f"<div class='insight'>💡 محصولات در بازه قیمتی <b>{_e(best)} تومان</b> بیشترین "
                   f"تعامل را دریافت می‌کنند. میانگین قیمت وزنی بر اساس تعامل: <b>{weighted}</b> — "
                   f"این عدد نشان می‌دهد مخاطبان شما به چه نقطه قیمتی واکنش بهتری دارند.</div>")

        stats = (f"<ul class='mini'>"
                 f"<li>کمترین قیمت: {_fmt_price(pricing['min'])}</li>"
                 f"<li>بیشترین قیمت: {_fmt_price(pricing['max'])}</li>"
                 f"<li>میانگین: {_fmt_price(pricing['mean'])}</li>"
                 f"<li>میانه: {_fmt_price(pricing['median'])}</li>"
                 f"<li>پست‌های بدون قیمت مشخص: {pricing.get('count_unpriced', 0)}</li>"
                 f"</ul>")

        return f"""
        <section class="section">
            <h2>۵. تحلیل قیمت‌گذاری</h2>
            <div class="two-col">
                <div class="chart-box">{chart}</div>
                <div>{stats}</div>
            </div>
            {insight}
        </section>
        """

    # ----------------------------------------------------------- hashtag chart
    def _hashtag_section(self, client):
        tags = client.get("hashtags", {})
        top_perf = tags.get("top_performing", [])
        most_used = tags.get("most_used", [])
        if not top_perf and not most_used:
            return ""

        perf_data = [(f"#{t['tag']}", t["avg_engagement"]) for t in top_perf[:8]]
        chart = charts.bar_chart(perf_data, title="Top Performing Hashtags (Avg Engagement)") if perf_data else ""


        used_chips = "".join(
            f"<span class='chip'>#{_e(t['tag'])} <b>({t['count']})</b></span>" for t in most_used[:15]
        )
        return f"""
        <section class="section">
            <h2>۶. تحلیل هشتگ و کلمات کلیدی</h2>
            <div class="chart-box">{chart}</div>
            <p class="sub-label">پرتکرارترین هشتگ‌ها:</p>
            <div class="chips">{used_chips}</div>
            <div class="insight">💡 هشتگ‌های پرتعامل را در پست‌های بیشتری استفاده کنید و هشتگ‌های کم‌بازده را با نمونه‌های موفق جایگزین کنید.</div>
        </section>
        """

    # ------------------------------------------------------------ demand signals
    def _demand_section(self, client):
        signals = client.get("demand_signals", {})
        if not signals:
            return ""
        hot = signals.get("posts_with_buyer_questions", [])
        rows = "".join(
            f"<tr><td>پست #{p['post_index']}</td><td>{p['questions']}</td>"
            f"<td>{_e(p['snippet'])}</td></tr>" for p in hot
        )
        table = (f"<table class='data-table'><thead><tr><th>پست</th>"
                 f"<th>تعداد پرسش خرید</th><th>موضوع</th></tr></thead><tbody>{rows}</tbody></table>"
                 if rows else "<p>پرسش خریدی در کامنت‌ها شناسایی نشد.</p>")

        return f"""
        <section class="section">
            <h2>۷. سیگنال‌های تقاضا (تحلیل سریع کل کامنت‌ها)</h2>
            <div class="stat-row">
                <div class="stat"><b>{signals.get('total_comments_scanned',0)}</b><span>کامنت بررسی‌شده</span></div>
                <div class="stat"><b>{signals.get('price_questions',0)}</b><span>پرسش قیمت</span></div>
                <div class="stat"><b>{signals.get('order_intents',0)}</b><span>قصد خرید</span></div>
                <div class="stat"><b>{signals.get('complaints',0)}</b><span>شکایت / نارضایتی</span></div>
            </div>
            <p class="sub-label">پست‌هایی با بیشترین پرسش خرید (اولویت پاسخگویی):</p>
            {table}
        </section>
        """

    # ------------------------------------------------------------ AI section
    def _ai_section(self, client):
        ai = client.get("ai_summary", {})
        note = client.get("ai_bi_note")
        if not ai or (not ai.get("total_leads") and not ai.get("top_inventory_gaps")
                      and not ai.get("top_objections")):
            if note:
                return f"""<section class="section"><h2>۸. هوش تجاری مبتنی بر هوش مصنوعی</h2>
                    <p class="muted">{_e(note)}</p></section>"""
            return ""

        # Leads
        leads = ai.get("leads", [])[:15]
        lead_rows = "".join(
            f"<tr><td>{_e(l.get('username','کاربر'))}</td>"
            f"<td>پست #{l.get('post','?')}</td>"
            f"<td>{_e(l.get('intent',''))}</td></tr>" for l in leads
        )
        leads_html = (f"<p class='sub-label'>💰 لیدهای فروش (مشتریان آماده خرید):</p>"
                      f"<table class='data-table'><thead><tr><th>کاربر</th><th>پست</th><th>خواسته</th></tr></thead>"
                      f"<tbody>{lead_rows}</tbody></table>" if lead_rows
                      else "<p>لید مشخصی شناسایی نشد.</p>")

        # Inventory gaps
        gaps = ai.get("top_inventory_gaps", [])
        gap_html = "".join(f"<li>{_e(g)} <span class='muted'>({c} بار درخواست)</span></li>"
                           for g, c in gaps)
        gap_block = (f"<p class='sub-label'>📦 نیازهای موجودی (محصولات مورد درخواست مشتری):</p>"
                     f"<ul class='bullets'>{gap_html}</ul>" if gap_html else "")

        # Objections
        objs = ai.get("top_objections", [])
        obj_html = "".join(f"<li>{_e(o)} <span class='muted'>({c} مورد)</span></li>"
                           for o, c in objs)
        obj_block = (f"<p class='sub-label'>⚠️ موانع و اعتراضات خرید:</p>"
                     f"<ul class='bullets'>{obj_html}</ul>" if obj_html else "")

        # Sentiment
        sent = ai.get("sentiment_breakdown", {})
        sent_chart = ""
        if sent:
            sent_en = {"positive": "Positive", "neutral": "Neutral", "negative": "Negative"}
            data = [(sent_en.get(k, k), v) for k, v in sent.items()]
            sent_chart = charts.donut_chart(data, title="Overall Comment Sentiment")


        pr = ai.get("price_resistance_total", 0)
        pr_note = (f"<div class='insight'>📉 مجموع شکایت‌های صریح از بالا بودن قیمت: <b>{pr} مورد</b>.</div>"
                   if pr else "")

        return f"""
        <section class="section">
            <h2>۸. هوش تجاری مبتنی بر هوش مصنوعی</h2>
            <p>تحلیل عمیق کامنت‌های پرطرفدارترین پست‌ها توسط مدل زبانی برای استخراج لید، تقاضا و موانع خرید.</p>
            <div class="two-col">
                <div>{leads_html}</div>
                <div class="chart-box">{sent_chart}</div>
            </div>
            {gap_block}
            {obj_block}
            {pr_note}
        </section>
        """

    # ------------------------------------------------------ competitor section
    def _competitor_section(self, client, comparison, competitors):
        metrics = comparison.get("metrics", {})
        client_row = metrics.get("client", {})
        comp_rows = metrics.get("competitors", [])

        # Comparison table
        header = "<tr><th>پیج</th><th>پست</th><th>میانگین تعامل</th><th>میانه تعامل</th><th>کل تعامل</th><th>میانگین قیمت</th><th>دسته برتر</th><th>روند</th></tr>"

        def make_row(r, is_client=False):
            cls = " class='client-row'" if is_client else ""
            price = _fmt_price(r["avg_price"]) if r.get("avg_price") else "—"
            name = ("⭐ @" + r["username"]) if is_client else "@" + r["username"]
            return (f"<tr{cls}><td>{_e(name)}</td><td>{r['posts']}</td>"
                    f"<td>{_fmt_num(r['avg_engagement'])}</td><td>{_fmt_num(r['median_engagement'])}</td>"
                    f"<td>{_fmt_num(r['total_engagement'])}</td><td>{price}</td>"
                    f"<td>{_e(r.get('star_category') or '—')}</td>"
                    f"<td>{TREND_FA.get(r.get('trend','n/a'))}</td></tr>")

        table_rows = make_row(client_row, True) + "".join(make_row(r) for r in comp_rows)

        # Grouped bar chart: avg engagement client vs competitors
        names = [client_row["username"]] + [r["username"] for r in comp_rows]
        eng_vals = [client_row["avg_engagement"]] + [r["avg_engagement"] for r in comp_rows]
        eng_chart = charts.grouped_bar_chart(
            names, [("Avg Engagement", eng_vals)],
            title="Avg Engagement vs Competitors"
        )


        # Positioning
        pos = comparison.get("positioning", {})
        pos_html = ""
        if pos:
            rank = pos.get("engagement_rank")
            field = pos.get("field_size")
            eng_vs = pos.get("engagement_vs_market_pct")
            pieces = []
            if rank:
                pieces.append(f"رتبه تعامل شما: <b>{rank} از {field}</b>")
            if eng_vs is not None:
                sign = "بالاتر" if eng_vs >= 0 else "پایین‌تر"
                pieces.append(f"تعامل شما <b>{abs(eng_vs)}٪ {sign}</b> از میانگین رقبا")
            if pos.get("price_position"):
                pp = {"premium": "پریمیوم (گران‌تر)", "budget": "اقتصادی (ارزان‌تر)",
                      "mid-market": "متوسط بازار"}.get(pos["price_position"], pos["price_position"])
                pieces.append(f"جایگاه قیمتی شما: <b>{pp}</b>")
            pos_html = "<div class='callout'><ul class='summary-list'>" + \
                       "".join(f"<li>{p}</li>" for p in pieces) + "</ul></div>"

        return f"""
        <section class="section page-break">
            <h2>۹. تحلیل رقابتی</h2>
            <p>مقایسه مستقیم پیج شما با رقبای انتخاب‌شده در بازار.</p>
            {pos_html}
            <div class="chart-box">{eng_chart}</div>
            <table class="data-table compare">
                <thead>{header}</thead>
                <tbody>{table_rows}</tbody>
            </table>
        </section>
        """

    # ------------------------------------------------------------ advice section
    def _advice_section(self, comparison):
        advice = comparison.get("advice", [])
        if not advice:
            return ""
        items = "".join(
            f"<div class='advice-card'><span class='advice-num'>{i+1}</span>"
            f"<p>{_e(a)}</p></div>"
            for i, a in enumerate(advice)
        )
        return f"""
        <section class="section">
            <h2>۱۰. توصیه‌های راهبردی</h2>
            <p>پیشنهادهای عملی و قابل اجرا بر اساس داده‌های پیج شما و مقایسه با رقبا.</p>
            <div class="advice-list">{items}</div>
        </section>
        """

    # ------------------------------------------------------------ top posts
    def _top_posts_section(self, client):
        top = client.get("top_posts", [])
        outliers = client.get("viral_outliers", [])
        if not top and not outliers:
            return ""

        def rows(items):
            return "".join(
                f"<tr><td>#{p['post_index']}</td><td>{_e(p['category'])}</td>"
                f"<td>{_fmt_price(p['price'])}</td><td>{_fmt_num(p['engagement'])}</td>"
                f"<td>{p['comment_count']}</td><td>{_e(p['snippet'])}</td></tr>"
                for p in items
            )

        header = ("<tr><th>پست</th><th>دسته</th><th>قیمت</th><th>تعامل</th>"
                  "<th>کامنت</th><th>موضوع</th></tr>")

        outlier_block = ""
        if outliers:
            outlier_block = f"""
            <p class="sub-label">🚀 پست‌های وایرال / تبلیغاتی (تعامل بسیار بالاتر از میانگین):</p>
            <table class="data-table"><thead>{header}</thead><tbody>{rows(outliers)}</tbody></table>
            """

        organic_block = ""
        if top:
            organic_block = f"""
            <p class="sub-label">🔥 برترین پست‌های ارگانیک:</p>
            <table class="data-table"><thead>{header}</thead><tbody>{rows(top)}</tbody></table>
            """

        return f"""
        <section class="section page-break">
            <h2>۱۱. برترین پست‌ها</h2>
            {outlier_block}
            {organic_block}
        </section>
        """

    def _footer(self, brand):
        year = datetime.now().year
        return f"""
        <section class="disclaimer">
            <p>این گزارش توسط موتور تحلیل <b>{_e(brand)}</b> و بر اساس داده‌های عمومی استخراج‌شده از پیج‌ها تهیه شده است.
            اعداد تعامل و قیمت بر پایه اطلاعات قابل مشاهده در زمان استخراج هستند.</p>
            <p class="copy">© {year} {_e(brand)} — گزارش محرمانه مخصوص مشتری</p>
        </section>
        """

    # ================================================================ styling
    def _wrap_html(self, body, username, brand):
        return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<title>{_e(brand)} - گزارش @{_e(username)}</title>
<style>
    {_font_face_css()}
    @page {{
        size: A4;
        margin: 1.5cm;
        @bottom-center {{ content: "صفحه " counter(page) " از " counter(pages); font-family: 'Vazirmatn', Tahoma, sans-serif; font-size: 9px; color: #999; }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
        font-family: 'Vazirmatn', Tahoma, Arial, sans-serif;
        line-height: 1.9; color: #2d3436; margin: 0;
        font-size: 13px; background: #fff;
    }}

    h1, h2, h3 {{ color: #1a2a4a; }}
    h2 {{
        font-size: 19px; border-right: 5px solid #2c6fbb;
        padding: 6px 12px 6px 0; margin: 30px 0 16px 0; background: #f4f8fc;
    }}
    .section {{ margin-bottom: 26px; }}
    .page-break {{ page-break-before: always; }}

    /* Cover */
    .cover {{
        text-align: center; padding: 90px 20px 60px 20px;
        background: linear-gradient(135deg, #1a2a4a 0%, #2c6fbb 100%);
        color: #fff; border-radius: 10px; margin-bottom: 30px;
        page-break-after: always;
    }}
    .cover-badge {{
        display: inline-block; letter-spacing: 3px; font-size: 13px;
        border: 1px solid rgba(255,255,255,.5); padding: 5px 18px;
        border-radius: 20px; margin-bottom: 30px;
    }}
    .cover-title {{ font-size: 34px; color: #fff; margin: 10px 0; }}
    .cover-sub {{ font-size: 15px; opacity: .9; margin-bottom: 40px; }}
    .cover-target {{ font-size: 20px; margin-bottom: 30px; }}
    .cover-target span {{ color: #ffd479; font-weight: bold; }}
    .cover-meta {{ display: flex; justify-content: center; gap: 30px; font-size: 13px; opacity: .85; }}

    /* Callout & insight */
    .callout {{ background: #f4f8fc; border: 1px solid #d6e4f0; border-radius: 8px; padding: 14px 18px; }}
    .insight {{
        background: #fff8e8; border-right: 4px solid #e08e0b;
        padding: 10px 14px; border-radius: 6px; margin-top: 12px; font-size: 12.5px;
    }}
    .summary-list li {{ margin: 6px 0; }}
    .muted {{ color: #888; font-size: 11px; }}
    .sub-label {{ font-weight: bold; color: #1a2a4a; margin: 16px 0 8px 0; }}

    /* KPI cards */
    .kpi-grid {{ display: flex; flex-wrap: wrap; gap: 12px; }}
    .kpi {{
        flex: 1 1 150px; background: #fff; border: 1px solid #e3e8ef;
        border-radius: 10px; padding: 14px; text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,.04);
    }}
    .kpi-val {{ font-size: 22px; font-weight: bold; color: #2c6fbb; }}
    .kpi-title {{ font-size: 12px; margin-top: 4px; color: #2d3436; font-weight: bold; }}
    .kpi-note {{ font-size: 10px; color: #999; }}

    /* Charts */
    .chart-box {{ background: #fff; border: 1px solid #eee; border-radius: 8px; padding: 12px; margin: 10px 0; }}
    .two-col {{ display: flex; gap: 16px; flex-wrap: wrap; }}
    .two-col > * {{ flex: 1 1 260px; }}

    /* Tables */
    .data-table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 12px; }}
    .data-table th {{ background: #1a2a4a; color: #fff; padding: 8px 6px; text-align: right; }}
    .data-table td {{ padding: 7px 6px; border-bottom: 1px solid #eee; }}
    .data-table tr:nth-child(even) td {{ background: #f8fafc; }}
    .compare .client-row td {{ background: #eaf3fb !important; font-weight: bold; }}

    /* Stat row */
    .stat-row {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 12px 0; }}
    .stat {{ flex: 1 1 120px; background: #f4f8fc; border-radius: 8px; padding: 12px; text-align: center; }}
    .stat b {{ display: block; font-size: 22px; color: #2c6fbb; }}
    .stat span {{ font-size: 11px; color: #666; }}

    /* Chips */
    .chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .chip {{ background: #eef3f9; border: 1px solid #d6e4f0; border-radius: 14px; padding: 3px 10px; font-size: 11px; }}

    .bullets li {{ margin: 4px 0; }}
    .mini {{ list-style: none; padding: 0; }}
    .mini li {{ padding: 5px 0; border-bottom: 1px dashed #eee; }}

    /* Advice */
    .advice-list {{ display: flex; flex-direction: column; gap: 10px; }}
    .advice-card {{
        display: flex; align-items: flex-start; gap: 12px;
        background: #f0f7f2; border-right: 4px solid #3aa76d;
        padding: 12px 14px; border-radius: 8px;
    }}
    .advice-num {{
        background: #3aa76d; color: #fff; min-width: 26px; height: 26px;
        border-radius: 50%; display: flex; align-items: center; justify-content: center;
        font-weight: bold; font-size: 13px;
    }}
    .advice-card p {{ margin: 0; font-size: 12.5px; }}

    /* Disclaimer */
    .disclaimer {{ margin-top: 40px; padding-top: 14px; border-top: 1px solid #eee; font-size: 10.5px; color: #999; }}
    .copy {{ text-align: center; margin-top: 8px; }}
</style>
</head>
<body>
{body}
</body>
</html>"""

    # -------------------------------------------- backward-compat entry point
    def generate_persian_report(self, target_username, trends, outliers, bi_results,
                                make_pdf=False):
        """Legacy shim kept so old callers don't break."""
        print("[!] generate_persian_report is deprecated; use generate_report(insights).")
        return None
