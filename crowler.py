from playwright.sync_api import sync_playwright
import time
from datetime import datetime
from adb_controlloer import BlueStacksController
import random

def check_target_status(url: str) -> dict:
    """Navigate to a profile page and return a summary dict.

    Keys:
        online (bool)    - whether the blue indicator is present
        name (str)       - current player name text
        code (str)       - unique player code (unchanging)
    """
    print(f"[*] Navigating to target profile: {url}")
    result = {"online": False, "name": None, "code": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto(url)

            # scrape name & code first
            name_el = page.query_selector(".txt_name.clamp")
            code_el = page.query_selector(".txt_code")
            if name_el:
                result["name"] = name_el.inner_text().strip()
            if code_el:
                result["code"] = code_el.inner_text().strip()

            # selector for online indicator
            target_selector = ".banner_user .alarm_status"
            element = page.wait_for_selector(target_selector, state="attached", timeout=5000)

            if element:
                bg_color = element.evaluate("el => window.getComputedStyle(el).backgroundColor")
                if bg_color == "rgb(0, 156, 254)":
                    print("[+] Target is currently ONLINE (Blue indicator active)!")
                    result["online"] = True
                else:
                    print(f"[-] Target is OFFLINE. Element exists but color is {bg_color}")
        except Exception:
            print("[-] Target is OFFLINE (Element not found or timeout).")
        finally:
            browser.close()

    return result

from concurrent.futures import ThreadPoolExecutor, as_completed


def check_multiple_status(urls: list[str], max_workers: int = 6) -> dict[str, dict]:
    """Check a list of profile URLs in parallel and return a mapping of URL->result dict.

    Each result dictionary contains the keys produced by :func:`check_target_status`.
    """
    results: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(check_target_status, url): url for url in urls}

        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results[url] = future.result()
            except Exception as exc:
                print(f"[!] Error checking {url}: {exc}")
                results[url] = {"online": False, "name": None, "code": None}
    return results


# when run as script we start the monitoring service
if __name__ == "__main__":
    # configuration
    targets = [
        # 芭蕾玲娜#aHe5L (Cleric)
        "https://maplestoryworlds.nexon.com/profile/aHe5L",
        # 嗵嗵#ayhlH (Crossbowman)
        "https://maplestoryworlds.nexon.com/profile/ayhlH",
        # Ballerina#clVnJ (Gunslinger)
        "https://maplestoryworlds.nexon.com/profile/clVnJ",
        # 超渡我#9OqUI (Page)
        "https://maplestoryworlds.nexon.com/profile/9OqUI",
        # 蘭若度母#1bLtH (Assassin)
        "https://maplestoryworlds.nexon.com/profile/1bLtH",
        # 漢娜醬晚餐吃筍絲弩肉飯#00TPK (Crossbowman)
        "https://maplestoryworlds.nexon.com/profile/00TPK",
    ]

    # how often to poll (seconds)
    CHECK_INTERVAL = 300  # 5 minutes

    # create the adb controller once
    controller = BlueStacksController()

    # keep track of which accounts we've messaged while they're online
    seen_online: set[str] = set()

    print("[+] starting monitor, checking every {} seconds".format(CHECK_INTERVAL))
    while True:
        statuses = check_multiple_status(targets, max_workers=5)
        now_str = datetime.now().strftime("%Y%m%d%H%M")
        for url, info in statuses.items():
            online = info.get("online")
            name = info.get("name") or ""
            code = info.get("code") or ""
            key = code or url
            if online:
                if key not in seen_online:
                    cmd_part = f"/w {name}{code}"
                    time_part = now_str
                    print(f"[*] {name} ({code}) just came online; sending: {cmd_part} | {time_part}")
                    controller.send_message(cmd_part)
                    controller.random_delay(1000, 2000)
                    controller.send_message(time_part)
                    controller.random_delay(500, 1000)
                    seen_online.add(key)
                else:
                    print(f"[*] {name} ({code}) still online, already messaged")
            else:
                if key in seen_online:
                    print(f"[*] {name} ({code}) went offline, clearing state")
                    seen_online.discard(key)
        # sleep a little bit randomised to avoid perfect 5-minute marks
        jitter = random.uniform(-10, 10)
        sleep_time = max(0, CHECK_INTERVAL + jitter)
        print(f"[+] sleeping {sleep_time:.1f}s before next check\n")
        time.sleep(sleep_time)
    # service runs indefinitely