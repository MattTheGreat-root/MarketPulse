import os
import re
import time
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from core.base_scraper import BaseScraper

class RubinoScraper(BaseScraper):
    def __init__(self, driver, target, output_dir="data"):
        super().__init__(driver, target, output_dir)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        safe_target = "".join(c for c in self.target if c.isalnum() or c in ('_', '-'))
        self.output_path = os.path.join(self.output_dir, f"{safe_target}_{timestamp}.csv")

    def navigate_to_page(self) -> bool:
        print(f"[*] Looking for page: @{self.target}")
        wait = WebDriverWait(self.driver, 10)

        try:
            self.driver.switch_to.default_content()
            time.sleep(0.5)

            vitrin_tab_xpath = "//button[.//span[text()='ویترین']]"
            vitrin_tab = wait.until(EC.element_to_be_clickable((By.XPATH, vitrin_tab_xpath)))
            self.driver.execute_script("arguments[0].click();", vitrin_tab)
            
            time.sleep(0.5)
            dummy_search_trigger_xpath = "//*[text()='جستجو' or contains(@placeholder, 'جستجو')]"
            dummy_search_trigger = wait.until(EC.element_to_be_clickable((By.XPATH, dummy_search_trigger_xpath)))
            self.driver.execute_script("arguments[0].click();", dummy_search_trigger)

            time.sleep(0.5)  
            
            actual_search_input_xpath = "//input[contains(@placeholder, 'جستجوی کاربر') or @type='text']"
            wait.until(EC.presence_of_element_located((By.XPATH, actual_search_input_xpath)))
            search_inputs = self.driver.find_elements(By.XPATH, actual_search_input_xpath)
            
            actual_search_input = None
            for inp in search_inputs:
                if inp.is_displayed():
                    actual_search_input = inp
                    break
                    
            if not actual_search_input:
                raise Exception("Search input box not found or not visible.")

            self.driver.execute_script("arguments[0].focus(); arguments[0].click();", actual_search_input)
            actual_search_input.clear()
            actual_search_input.send_keys(self.target)
            actual_search_input.send_keys(Keys.ENTER)

            time.sleep(1.5)

            # XPath with case-insensitive matching: translate both the element text
            # and the target to lowercase before comparing. This prevents failures
            # when the user types "Faiaz9090" but Rubika returns "faiaz9090".
            target_lower = self.target.lower()
            case_insensitive_xpath = (
                f"//div[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{target_lower}')] | "
                f"//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{target_lower}')]"
            )
            target_profile_item = wait.until(EC.presence_of_element_located((By.XPATH, case_insensitive_xpath)))

            self.driver.execute_script("arguments[0].click();", target_profile_item)

            time.sleep(1.5)
            print(f"[+] Reached profile @{self.target}.")
            return True

        except Exception as e:
            print(f"[!] Error when trying to navigate_to_page: {str(e)}")
            self.driver.get("https://m.rubika.ir/")
            time.sleep(2)
            return False

    def _find_scrollable_ancestor(self):
        return self.driver.execute_script(
            """
            let exactContainer = document.querySelector('.rtl-l3f8vc');
            if (exactContainer) return exactContainer;
            
            let virtualized = document.querySelector('div[style*="overflow: auto"][style*="will-change: transform"]');
            if (virtualized) return virtualized;

            return null;
            """
        )

    def scroll_and_load_posts(self, scroll_cycles=2, pause_time=1.0):
        """
        Optimized scroll cycles down from 5 to 2, expanding step distance for faster loads.
        """
        container = self._find_scrollable_ancestor()

        if container is None:
            for i in range(scroll_cycles):
                self.driver.execute_script("window.scrollBy({top: 350, behavior: 'smooth'});")
                time.sleep(pause_time)
            return

        for i in range(scroll_cycles):
            self.driver.execute_script("arguments[0].scrollBy({top: 350, behavior: 'smooth'});", container)
            time.sleep(pause_time)

    def _wait_for_post_images_loaded(self, timeout=10):
        WebDriverWait(self.driver, timeout).until(
            lambda d: d.execute_script(
                """
                let imgs = document.querySelectorAll('img[src*="/picture/"]');
                if (imgs.length === 0) return false;
                return Array.from(imgs).every(img => img.complete && img.naturalWidth > 0);
                """
            )
        )

    def find_post_tiles(self):
        try:
            self._wait_for_post_images_loaded()
        except Exception:
            pass # Keep moving if images take too long but placeholders are clickable

        xpath = (
            "//div[@width and @height]"
            "[.//img[contains(@src, '/picture/')]]"
            "[not(ancestor::nav) and not(ancestor::header)]"
        )
        candidates = self.driver.find_elements(By.XPATH, xpath)

        size_filtered = []
        for tile in candidates:
            try:
                w = float(tile.get_attribute("width"))
                h = float(tile.get_attribute("height"))
                if w > 100 and abs(w - h) <= 2 and tile.is_displayed():
                    size_filtered.append(tile)
            except (TypeError, ValueError):
                continue

        if not size_filtered:
            return []

        dedup_info = self.driver.execute_script(
            """
            let els = arguments[0];
            return els.map(el => {
                let rect = el.getBoundingClientRect();
                return [Math.round(rect.top / 5) * 5, Math.round(rect.left / 5) * 5];
            });
            """,
            size_filtered,
        )

        by_position = {}
        for tile, (top, left) in zip(size_filtered, dedup_info):
            by_position[(top, left)] = tile  

        ordered_positions = sorted(by_position.keys(), key=lambda pos: (pos[0], -pos[1]))
        deduped_tiles = [by_position[pos] for pos in ordered_positions]

        topmost_flags = self.driver.execute_script(
            """
            let els = arguments[0];
            return els.map(el => {
                let rect = el.getBoundingClientRect();
                let cx = rect.left + rect.width / 2;
                let cy = rect.top + rect.height / 2;
                let topEl = document.elementFromPoint(cx, cy);
                return !!topEl && (topEl === el || el.contains(topEl));
            });
            """,
            deduped_tiles,
        )

        return [tile for tile, is_topmost in zip(deduped_tiles, topmost_flags) if is_topmost]

    def count_available_tiles(self):
        return len(self.find_post_tiles())

    def scrape_all_posts(self, max_posts=None):
        seen_srcs = set()
        results = []
        stagnant_rounds = 0
        max_stagnant_rounds = 2 # Reduced to terminate faster on empty profiles

        while True:
            if max_posts is not None and len(results) >= max_posts:
                break

            tiles = self.find_post_tiles()
            target_index = None
            target_src = None
            for i, tile in enumerate(tiles):
                try:
                    src = tile.find_element(By.TAG_NAME, "img").get_attribute("src")
                except Exception:
                    continue
                if src and src not in seen_srcs:
                    target_index = i
                    target_src = src
                    break

            if target_index is None:
                stagnant_rounds += 1
                if stagnant_rounds >= max_stagnant_rounds:
                    print("[*] No new posts found. Finishing extraction.")
                    break
                self.scroll_and_load_posts(scroll_cycles=1, pause_time=1.0)
                continue

            stagnant_rounds = 0
            seen_srcs.add(target_src)

            if self.open_post_by_index(target_index):
                data = self.extract_single_post_data()
                if data:
                    # Enforce final column order: post_index, description, price, engagement, comments
                    ordered = {
                        "post_index": len(results) + 1,
                        "description": data.get("description", ""),
                        "price": data.get("price", "None"),
                        "engagement": data.get("engagement", 0),
                        "comments": data.get("comments", ""),
                    }
                    results.append(ordered)
                    print(f"[+] Scraped {len(results)}: post_index={ordered['post_index']} "
                          f"price={ordered['price']} engagement={ordered['engagement']}")

                self.go_back_to_grid()

        return results

    def _click_tile_with_retry(self, index, attempts=3):
        from selenium.common.exceptions import (
            ElementClickInterceptedException,
            StaleElementReferenceException,
        )

        for attempt in range(1, attempts + 1):
            tiles = self.find_post_tiles()
            if not tiles or index >= len(tiles):
                time.sleep(0.3)
                continue

            target_tile = tiles[index]
            try:
                target_tile.click()
                return True
            except (ElementClickInterceptedException, StaleElementReferenceException):
                time.sleep(0.2)

        return False

    def open_post_by_index(self, index):
        try:
            success = self._click_tile_with_retry(index, attempts=3)
            if not success:
                return False

            WebDriverWait(self.driver, 4).until(
                lambda d: (
                    "لایک" in d.execute_script("return document.body.innerText;") or
                    "مشاهده" in d.execute_script("return document.body.innerText;")
                )
            )
            time.sleep(0.4)
            return True
        except Exception:
            return False

    def go_back_to_grid(self):
        try:
            candidates = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'rtl-1x9eqjj')]")
            in_viewport = self.driver.execute_script(
                """
                let els = arguments[0];
                return els.map(el => {
                    let rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0 &&
                        rect.left >= -1 && rect.left < window.innerWidth;
                });
                """,
                candidates,
            )
            visible_candidates = [el for el, ok in zip(candidates, in_viewport) if ok]

            if not visible_candidates:
                self.driver.back()
                time.sleep(0.8)
                return

            back_button = visible_candidates[0]
            try:
                self.driver.execute_script("arguments[0].click();", back_button)
                time.sleep(0.8)
            except Exception:
                self.driver.back()
                time.sleep(0.8)
        except Exception:
            self.driver.back()
            time.sleep(0.8)

    def _parse_engagement_text(self, text_content):
        # 1. Neutralize all invisible characters and Arabic-variants
        text = text_content.replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ')
        
        # 2. Universal number pattern (Includes Persian digits, commas, dots, slashes, and Persian commas)
        num_pattern = r"([\d\u0660-\u0669\u06f0-\u06f9,\./،]+)"
        
        # STRATEGY A: Find keywords ("قیمت", "مبلغ", "سرویس") followed by a number within 25 characters
        # [^\d...] ensures we gracefully skip over emojis, spaces, and colons until we hit the number
        match_a = re.search(r"(?:قیمت|مبلغ|بها|سرویس)[^\d\u0660-\u0669\u06f0-\u06f9]{0,25}?" + num_pattern, text)
        
        # STRATEGY B: Fallback - Find ANY number immediately followed by currency words
        match_b = re.search(num_pattern + r"\s*(?:تومان|تومانی|هزار|میلیون|ریال|T|t)", text)
        
        # Pick the best extraction
        best_match = match_a if match_a else match_b
        
        price = "None"
        if best_match:
            # group(1) guarantees we are ONLY extracting the number, ignoring the words around it
            raw_price = best_match.group(1)
            clean = re.sub(r"[,/\.،]", "", raw_price)
            price_int = self._safe_int(self._convert_persian_nums(clean))

            # Only treat as a valid price if we actually parsed a number.
            if price_int is not None:
                # MULTIPLIER LOGIC: Lock the context window strictly to the 25 chars AFTER the number
                end_idx = best_match.end(1)
                context = text[end_idx : end_idx + 25].lower()

                if 'میلیارد' in context:
                    price_int *= 1000000000
                elif 'میلیون' in context or 'm' in context:
                    price_int *= 1000000
                elif 'هزار' in context or 'k' in context:
                    price_int *= 1000

                price = str(price_int)

        # Extract Likes & Comments safely (never raise on malformed text)
        likes_match = re.search(r"([\d\u0660-\u0669\u06f0-\u06f9,\./،]+)\s*(?:لایک|مشاهده)", text)
        likes_raw = self._convert_persian_nums(re.sub(r"[,/\.،]", "", likes_match.group(1))) if likes_match else ""
        likes = self._safe_int(likes_raw) or 0

        comments_match = re.search(r"([\d\u0660-\u0669\u06f0-\u06f9,\./،]+)\s*کامنت", text)
        comments_raw = self._convert_persian_nums(re.sub(r"[,/\.،]", "", comments_match.group(1))) if comments_match else ""
        comments = self._safe_int(comments_raw) or 0

        return {
            "price": price if price != "None" else "None",
            "likes": likes,
            "comments": comments,
        }

    @staticmethod
    def _safe_int(value):
        """
        Best-effort int conversion. Strips any non-digit characters and returns
        None if nothing numeric remains, so callers never hit `int('')` crashes.
        """
        if value is None:
            return None
        digits = re.sub(r"\D", "", str(value))
        if not digits:
            return None
        try:
            return int(digits)
        except (ValueError, TypeError):
            return None


    def _open_comment_section(self):
        try:
            target = self.driver.execute_script(
                """
                let paths = document.querySelectorAll("path[d^='M2.678 11.894']");
                let visible = [];
                for (let p of paths) {
                    let svg = p.closest('svg');
                    if (!svg) continue;
                    let rect = svg.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0 && rect.left >= 0 && rect.left < window.innerWidth) {
                        visible.push(svg);
                    }
                }
                if (visible.length === 0) return null;
                
                let start = visible[visible.length - 1]; 
                let node = start.parentElement;
                let depth = 0;
                
                while (node && node !== document.body && depth < 4) {
                    if (window.getComputedStyle(node).cursor === 'pointer' || node.tagName === 'BUTTON') {
                        return node;
                    }
                    node = node.parentElement;
                    depth++;
                }
                return start;
                """
            )

            if not target:
                return False

            self.driver.execute_script(
                """
                let el = arguments[0];
                el.scrollIntoView({block: 'center'});
                el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
                """,
                target,
            )

            try:
                # FIX: Wait for EITHER the RTL or LTR comment container to appear
                WebDriverWait(self.driver, 2.5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.rtl-5lyezw, div.rtl-15m2bl8"))
                )
            except Exception:
                pass
                
            time.sleep(0.5)
            return True
        except Exception:
            return False

    def _find_comments_scrollable(self):
        return self.driver.execute_script(
            """
            // FIX: Search for either comment class to find the scrollable container
            let row = document.querySelector('div.rtl-5lyezw, div.rtl-15m2bl8');
            if (!row) return null;
            let node = row.parentElement;
            while (node && node !== document.body) {
                let style = window.getComputedStyle(node);
                if ((style.overflowY === 'auto' || style.overflowY === 'scroll')
                    && node.scrollHeight > node.clientHeight) {
                    return node;
                }
                node = node.parentElement;
            }
            return null;
            """
        )

    def _scroll_comments(self, pause_time=1.0):
        container = self._find_comments_scrollable()
        if container is not None:
            self.driver.execute_script(
                "arguments[0].scrollBy({top: 400, behavior: 'smooth'});", container
            )
        else:
            self.driver.execute_script("window.scrollBy({top: 400, behavior: 'smooth'});")
        time.sleep(pause_time)

    def _collect_comments_and_desc(self, max_comments=10):
        description = ""
        comments = []
        seen = set()

        if not self._open_comment_section():
            return description, comments

        stagnant_rounds = 0
        max_stagnant_rounds = 3

        while len(comments) < max_comments and stagnant_rounds < max_stagnant_rounds:
            # Grab all rows that are either RTL or LTR comments (and the caption)
            rows = self.driver.find_elements(By.CSS_SELECTOR, "div.rtl-5lyezw, div.rtl-15m2bl8")
            
            if not rows:
                break
                
            before = len(comments)

            for row in rows:
                # FILTER: Real comments have a timestamp/reply block (rtl-1um1bzv). The caption does not.
                try:
                    reply_block = row.find_elements(By.CSS_SELECTOR, "div.rtl-1um1bzv")
                    is_caption = len(reply_block) == 0
                except Exception:
                    is_caption = False

                try:
                    user = row.find_element(By.CSS_SELECTOR, "span.rtl-19gb1ua").text.strip()
                except Exception:
                    user = ""
                try:
                    text = row.find_element(By.CSS_SELECTOR, "span.rtl-1br88u2").text.strip()
                except Exception:
                    text = ""

                if not text:
                    continue

                # If it's the caption, save it to the description variable and skip adding to comments
                if is_caption:
                    if not description:
                        description = text
                    continue

                # Process as a normal comment
                key = (user, text)
                if key in seen or not (user or text):
                    continue

                seen.add(key)
                comments.append(f"{user}: {text}" if user else text)
                if len(comments) >= max_comments:
                    break

            if len(comments) >= max_comments:
                break

            if len(comments) == before:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0

            self._scroll_comments(pause_time=1.0)

        self._close_comment_section()
        return description, comments[:max_comments]
    
    def _close_comment_section(self):
        max_attempts = 3
        
        for _ in range(max_attempts):
            # FIX: Check if either LTR or RTL comment rows still exist on screen
            comments_open = self.driver.execute_script(
                "return document.querySelectorAll('div.rtl-5lyezw, div.rtl-15m2bl8').length > 0;"
            )
            
            if not comments_open:
                time.sleep(0.4)
                return

            try:
                candidates = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'rtl-1x9eqjj')]")
                visible_flags = self.driver.execute_script(
                    """
                    let els = arguments[0];
                    return els.map(el => {
                        let rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0 &&
                            rect.left >= -1 && rect.left < window.innerWidth;
                    });
                    """,
                    candidates,
                )
                visible = [el for el, ok in zip(candidates, visible_flags) if ok]

                if visible:
                    self.driver.execute_script("arguments[0].click();", visible[-1])
                else:
                    self.driver.back()
                    
            except Exception:
                self.driver.back()
            
            time.sleep(0.8)

        try:
            # FIX: Ensure both classes are gone before moving on
            WebDriverWait(self.driver, 2).until_not(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.rtl-5lyezw, div.rtl-15m2bl8"))
            )
        except Exception:
            pass

    def extract_single_post_data(self):
        # 1. Open comments first to get the full, un-truncated description and the comments
        description, comment_list = self._collect_comments_and_desc(max_comments=10)

        # 2. Get the main post view text (for the likes and total comments count)
        text_content = self.driver.execute_script("return document.body.innerText;")
        
        # 3. Combine them so the regex can find the price even if it was truncated on the main view
        combined_text = description + " \n " + text_content
        engagement_info = self._parse_engagement_text(combined_text)

        likes = self._safe_int(engagement_info.get("likes", 0)) or 0
        comment_count = self._safe_int(engagement_info.get("comments", 0)) or 0
        engagement = likes + comment_count

        return {
            "description": description,
            "price": engagement_info["price"],
            "engagement": engagement,
            "comments": "\n".join(comment_list),
        }