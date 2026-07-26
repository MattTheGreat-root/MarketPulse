import os
import pandas as pd
import markdown
import pdfkit

class ReportGenerator:
    def __init__(self, output_dir="reports"):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def generate_persian_report(self, target_username: str, trends: pd.DataFrame, outliers: pd.DataFrame, bi_results: dict, make_pdf: bool = False):
        report_path = os.path.join(self.output_dir, f"{target_username}_market_report.md")
        
        # 1. Build the Markdown content in memory
        md_text = f"# 📊 گزارش تحلیل کسب‌وکار و فروش\n"
        md_text += f"**پیج هدف:** `@{target_username}`\n\n---\n\n"

        # Outliers Section
        md_text += "## 🚀 پست‌های وایرال و تبلیغاتی (خارج از محدوده ارگانیک)\n"
        md_text += "> این پست‌ها تعاملی بسیار بالاتر از میانگین پیج داشته‌اند و معمولاً نشان‌دهنده تبلیغات، پین شدن یا وایرال شدن هستند.\n\n"
        if not outliers.empty:
            for _, row in outliers.iterrows():
                price_str = f"{int(row['price']):,} تومان" if row['price'] != "None" else "نامشخص"
                md_text += f"- **پست شماره {int(row['post_index'])}** | 💰 قیمت: {price_str} | ❤️ تعامل: {int(row['engagement']):,}\n"
        else:
            md_text += "- 🔹 هیچ پست وایرال یا تبلیغاتی یافت نشد.\n"
        md_text += "\n"

        # Organic Trends Section
        md_text += "## 🔥 برترین پست‌های ارگانیک (پرطرفدار)\n"
        md_text += "> این محصولات به صورت طبیعی بیشترین توجه و تقاضا را از سمت مخاطب جذب کرده‌اند.\n\n"
        if not trends.empty:
            for _, row in trends.iterrows():
                price_str = f"{int(row['price']):,} تومان" if row['price'] != "None" else "نامشخص"
                md_text += f"- **پست شماره {int(row['post_index'])}** | 💰 قیمت: {price_str} | ❤️ تعامل: {int(row['engagement']):,}\n"
        else:
            md_text += "- 🔹 داده‌ای برای پست‌های ارگانیک یافت نشد.\n"
        md_text += "\n"

        # Business Intelligence Section
        md_text += "## 🧠 هوش تجاری و تحلیل رفتار مشتریان\n"
        md_text += "> استخراج شده توسط هوش مصنوعی بر اساس کامنت‌های پست‌های پرطرفدار.\n\n"
        if bi_results:
            for post_idx, bi in bi_results.items():
                md_text += f"### 📍 تحلیل کامنت‌های پست شماره {post_idx}\n"
                if "error" in bi:
                    md_text += f"- ⚠️ **خطا در پردازش:** {bi['error']}\n\n"
                    continue

                leads = bi.get("leads", [])
                md_text += "#### 💰 لیدهای فروش (مشتریان آماده خرید):\n"
                if leads:
                    for lead in leads:
                        username = lead.get('username', 'کاربر')
                        intent = lead.get('intent', 'درخواست نامشخص')
                        md_text += f"- **{username}**: {intent}\n"
                else:
                    md_text += "- 🔸 لید فروشی در این پست یافت نشد.\n"

                gaps = bi.get("inventory_gaps", [])
                md_text += "\n#### 📦 نیازهای موجودی (درخواست رنگ، سایز، مدل):\n"
                if gaps:
                    for gap in gaps:
                        md_text += f"- {gap}\n"
                else:
                    md_text += "- 🔸 درخواستی برای موجودی جدید ثبت نشده است.\n"

                objections = bi.get("objections", [])
                md_text += "\n#### ⚠️ اعتراضات و موانع خرید:\n"
                if objections:
                    for obj in objections:
                        md_text += f"- {obj}\n"
                else:
                    md_text += "- 🔸 مانع خرید یا اعتراضی یافت نشد.\n"

                price_res = bi.get("price_resistance_count", 0)
                md_text += f"\n#### 📉 تعداد شکایات از قیمت بالا: **{price_res} مورد**\n\n---\n\n"
        else:
            md_text += "- 🔹 هیچ تحلیل هوش مصنوعی برای کامنت‌ها انجام نشده است.\n"

        # 2. Save Markdown
        with open(report_path, "w", encoding="utf-8-sig") as f:
            f.write(md_text)
        print(f"[+] Persian Markdown report generated at: {report_path}")

        # 3. Generate PDF if requested
        if make_pdf:
            html_path = report_path.replace(".md", ".html")
            pdf_path = report_path.replace(".md", ".pdf")
            
            # Convert Markdown to HTML and inject RTL Persian CSS styling
            html_body = markdown.markdown(md_text)
            styled_html = f"""
            <!DOCTYPE html>
            <html lang="fa" dir="rtl">
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{ font-family: Tahoma, Arial, sans-serif; line-height: 1.8; padding: 20px; color: #333; }}
                    h1, h2, h3, h4 {{ color: #2c3e50; }}
                    blockquote {{ background: #f9f9f9; border-right: 5px solid #3498db; padding: 10px 15px; margin: 0 0 20px 0; }}
                    hr {{ border: 0; height: 1px; background: #e0e0e0; margin: 20px 0; }}
                </style>
            </head>
            <body>
                {html_body}
            </body>
            </html>
            """
            
            with open(html_path, "w", encoding="utf-8-sig") as f:
                f.write(styled_html)
                
            try:
                # Disable warning outputs from wkhtmltopdf
                options = {'encoding': "UTF-8", 'quiet': ''}
                pdfkit.from_file(html_path, pdf_path, options=options)
                print(f"[+] Persian PDF report generated at: {pdf_path}")
                # Clean up the temporary HTML file if PDF was successful
                os.remove(html_path)
            except Exception:
                print(f"[!] 'wkhtmltopdf' is missing or failed. PDF skipped.")
                print(f"[+] Fallback: Styled HTML file saved at: {html_path} (Open in Chrome and Ctrl+P to save as PDF)")

        return report_path