import time
from selenium.webdriver.common.by import By

class RubikaAuth:
    def __init__(self, driver):
        """
        Takes a raw, unauthenticated driver from the BrowserManager.
        """
        self.driver = driver
        self.base_url = "https://m.rubika.ir/"

    def verify_session(self):
        print("[*] Navigating to Rubika for session verification...")
        self.driver.get(self.base_url)
        time.sleep(3)

        # Check for login fields
        needs_login = self.driver.find_elements(By.XPATH, "//input[@type='tel' or @name='phone_number']")
        
        if "login" in self.driver.current_url or needs_login:
            print("[!] ==> Not logged in!")
            input("[?] Press ENTER *ONLY* after you have successfully logged in... ")
            print("[+] Session saved.")
        else:
            print("[+] Already logged in. Profile works.")
            
        return self.driver