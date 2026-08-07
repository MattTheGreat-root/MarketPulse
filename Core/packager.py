import os
import glob
import zipfile
from datetime import datetime


class ClientPackager:
    def __init__(self, data_dir="data", reports_dir="reports", output_dir="deliverables"):
        self.data_dir = data_dir
        self.reports_dir = reports_dir
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _get_latest_file(self, directory: str, pattern: str):
        files = glob.glob(os.path.join(directory, pattern))
        if not files:
            return None
        # Use modification time: reports are now timestamped per run, so there
        # can be several for the same profile. mtime reliably identifies the
        # freshest one to ship.
        return max(files, key=os.path.getmtime)


    def package_deliverables(self, target_username: str, competitor_usernames=None,
                             include_html_fallback=True, mini: bool = False):
        """
        Bundles the client's report (PDF, and HTML as fallback) together with
        the raw Excel data for the client and any competitors into one zip.
        """
        competitor_usernames = competitor_usernames or []
        print(f"\n[*] Packaging client deliverables for @{target_username}...")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_label = "mini_report" if mini else "market_report"
        zip_filename = f"{target_username}_Client_Deliverable_{timestamp}.zip"
        zip_path = os.path.join(self.output_dir, zip_filename)

        added_any = False
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                # --- Report (PDF preferred, HTML fallback) --------------------
                # Reports are timestamped ({username}_{label}_{ts}.pdf), so glob
                # with a wildcard and let _get_latest_file pick the freshest.
                pdf = self._get_latest_file(self.reports_dir,
                                           f"{target_username}_{report_label}_*.pdf")
                if pdf:
                    zipf.write(pdf, arcname=os.path.basename(pdf))
                    print(f"  -> Added report (PDF): {os.path.basename(pdf)}")
                    added_any = True
                elif include_html_fallback:
                    html = self._get_latest_file(self.reports_dir,
                                                f"{target_username}_{report_label}_*.html")
                    if html:
                        zipf.write(html, arcname=os.path.basename(html))
                        print(f"  -> Added report (HTML): {os.path.basename(html)}")
                        added_any = True

                if not pdf:
                    print("  -> [!] No PDF report found.")

                # --- Client raw data ------------------------------------------
                client_xlsx = self._get_latest_file(self.data_dir, f"{target_username}_*.xlsx")
                if client_xlsx:
                    zipf.write(client_xlsx, arcname=f"data/{os.path.basename(client_xlsx)}")
                    print(f"  -> Added client data: {os.path.basename(client_xlsx)}")
                    added_any = True

                # --- Competitor raw data --------------------------------------
                for comp in competitor_usernames:
                    comp_xlsx = self._get_latest_file(self.data_dir, f"{comp}_*.xlsx")
                    if comp_xlsx:
                        zipf.write(comp_xlsx, arcname=f"data/competitors/{os.path.basename(comp_xlsx)}")
                        print(f"  -> Added competitor data: {os.path.basename(comp_xlsx)}")
                        added_any = True

            if not added_any:
                os.remove(zip_path)
                print("[!] Nothing to package. Zip skipped.")
                return None

            print(f"[+] Successfully created client zip package at: {zip_path}")
            return zip_path

        except Exception as e:
            print(f"[!] Failed to create zip package: {e}")
            return None
