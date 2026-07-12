import os
import sys
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.chrome.service import Service

class BrowserManager:
    def __init__(self, platform_name: str):
        """
        Creates an isolated profile for the specific platform to prevent cookie overlap.
        """
        self.profile_path = os.path.abspath(f'chrome_profile_{platform_name}')
        
        if not os.path.exists(self.profile_path):
            os.makedirs(self.profile_path)

    def get_driver(self):
        print(f"[System] Firing up Chrome for {os.path.basename(self.profile_path)}...")
        opt = Options()
        opt.add_experimental_option("detach", True) 
        
        opt.add_experimental_option("excludeSwitches", ["enable-automation"])
        opt.add_argument("--disable-blink-features=AutomationControlled")
        
        opt.add_argument(f"--user-data-dir={self.profile_path}")
        opt.add_argument("--profile-directory=Default")
                
        try:
            local_driver = os.path.join(os.getcwd(), "chromedriver.exe")
            
            if os.path.exists(local_driver):
                print("[System] Local chromedriver.exe found. Bypassing network download.")
                service = Service(local_driver)
                driver = webdriver.Chrome(service=service, options=opt)
            else:
                driver = webdriver.Chrome(options=opt)
                
            driver.maximize_window()
            return driver
            
        except SessionNotCreatedException:
            print("\n" + "="*50)
            print("[FATAL ERROR] Chrome is already running!")
            print("Chrome locks the profile folder to a single process.")
            print("You must close the existing Chrome window before running this script.")
            print("="*50 + "\n")
            sys.exit(1)