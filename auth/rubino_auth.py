import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

class RubikaAuth:
    def __init__(self, profile_path='chrome_profile'):
        self.profile_path = os.path.abspath(profile_path)
        self.base_url = "https://m.rubika.ir/"
        
        if not os.path.exists(self.profile_path):
            os.makedirs(self.profile_path)
            
        self.driver = self._init_driver()

    def _init_driver(self):
        from selenium.common.exceptions import SessionNotCreatedException
        from selenium.webdriver.chrome.service import Service
        import sys
        import os
        
        print("[System] Firing up Chrome...")
        opt = Options()
        opt.add_experimental_option("detach", True) 
        
        opt.add_experimental_option("excludeSwitches", ["enable-automation"])
        opt.add_argument("--disable-blink-features=AutomationControlled")
        
        opt.add_argument(f"--user-data-dir={self.profile_path}")
        opt.add_argument("--profile-directory=Default")
                
        try:
            local_driver = os.path.join(os.getcwd(), "chromedriver.exe")
            
            if os.path.exists(local_driver):
                print("[System] Local chromedriver.exe found. Bypassing network download (No VPN needed).")
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
            print("You must close the existing Chrome window (Cmd+Q / Alt+F4) before running this script.")
            print("="*50 + "\n")
            sys.exit(1)

    def login(self):
        self.driver.get(self.base_url)
        time.sleep(3)

        needs_login = self.driver.find_elements(By.XPATH, "//input[@type='tel' or @name='phone_number']")
        
        if "login" in self.driver.current_url or needs_login:
            print("==> Not logged in!")
            input("Press ENTER *ONLY* after you have successfuly logged in... ")
            print("Session saved.")
        else:
            print("Already logged in. Profile works.")
            
        return self.driver