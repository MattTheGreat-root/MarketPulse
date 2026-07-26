import os
import glob
import zipfile
from datetime import datetime

class ClientPackager:
    def __init__(self, data_dir="data", reports_dir="reports", output_dir="deliverables"):
        self.data_dir = data_dir
        self.reports_dir = reports_dir
        self.output_dir = output_dir

        # Ensure the deliverables directory exists
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def _get_latest_file(self, directory: str, pattern: str):
        """Finds the most recently created file matching the pattern in the given directory."""
        search_pattern = os.path.join(directory, pattern)
        files = glob.glob(search_pattern)
        if not files:
            return None
        return max(files, key=os.path.getctime)

    def package_deliverables(self, target_username: str):
        """Finds the latest Excel data and PDF report and zips them for the client."""
        print(f"\n[*] Packaging client deliverables for @{target_username}...")

        # Find the latest files
        latest_xlsx = self._get_latest_file(self.data_dir, f"{target_username}_*.xlsx")
        latest_pdf = self._get_latest_file(self.reports_dir, f"{target_username}_market_report.pdf")

        if not latest_xlsx and not latest_pdf:
            print("[!] No XLSX or PDF found to zip. Packaging skipped.")
            return None

        # Create the Zip filename with a timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"{target_username}_Client_Deliverable_{timestamp}.zip"
        zip_path = os.path.join(self.output_dir, zip_filename)

        try:
            # ZIP_DEFLATED applies standard compression to make the file size smaller
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                if latest_pdf:
                    zipf.write(latest_pdf, arcname=os.path.basename(latest_pdf))
                    print(f"  -> Added report: {os.path.basename(latest_pdf)}")
                else:
                    print("  -> [!] Warning: No PDF report found to add.")

                if latest_xlsx:
                    zipf.write(latest_xlsx, arcname=os.path.basename(latest_xlsx))
                    print(f"  -> Added raw data: {os.path.basename(latest_xlsx)}")
                else:
                    print("  -> [!] Warning: No Excel file found to add.")

            print(f"[+] Successfully created client zip package at: {zip_path}")
            return zip_path
            
        except Exception as e:
            print(f"[!] Failed to create zip package: {e}")
            return None