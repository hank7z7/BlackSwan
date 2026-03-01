from playwright.sync_api import sync_playwright
import time
from datetime import datetime
from adb_controlloer import BlueStacksController
from ocr_engine import OCREngine
from notifier import update_dashboard
import random
import re

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
        "https://maplestoryworlds.nexon.com/profile/aHe5L",
        "https://maplestoryworlds.nexon.com/profile/ayhlH",
        "https://maplestoryworlds.nexon.com/profile/clVnJ",
        "https://maplestoryworlds.nexon.com/profile/9OqUI",
        "https://maplestoryworlds.nexon.com/profile/1bLtH",
        "https://maplestoryworlds.nexon.com/profile/AmvEH",
    ]

    # intervals
    CHECK_INTERVAL = 300  # seconds (5 minutes) -> fetch statuses
    SEND_INTERVAL = 90    # seconds (1 minute)  -> send messages to online accounts

    # create the adb controller once
    controller = BlueStacksController()
    # create OCR engine (uses adb to capture screen)
    ocr = OCREngine()

    # track last send timestamp per account (by code or url)
    last_sent: dict[str, float] = {}

    # record last OCR-detected channel per account (by code or url)
    last_channel: dict[str, str] = {}

    # latest known statuses (url -> info dict)
    statuses: dict[str, dict] = {}

    print(f"[+] starting monitor: fetch every {CHECK_INTERVAL}s, send every {SEND_INTERVAL}s")
    next_check_at = 0.0
    next_check_at = 0.0
    while True:
        now = time.time()

        # fetch statuses on schedule
        if now >= next_check_at:
            print(f"[*] fetching statuses at {datetime.now().isoformat()}...")
            try:
                statuses = check_multiple_status(targets, max_workers=6)
            except Exception as e:
                print(f"[!] failed to update statuses: {e}")
                statuses = {}
            # schedule next check with small jitter
            jitter = random.uniform(-5, 5)
            next_check_at = now + CHECK_INTERVAL + jitter

        # iterate known statuses and send to online accounts every SEND_INTERVAL
        for url, info in list(statuses.items()):
            online = bool(info.get("online"))
            name = info.get("name") or ""
            code = info.get("code") or ""
            account_id = code or url

            if online:
                last = last_sent.get(account_id, 0.0)
                if now - last >= SEND_INTERVAL:
                    now_str = datetime.now().strftime("%m%d%H%M%S")
                    cmd_part = f"/w {name}{code}"
                    time_part = now_str
                    print(f"[*] ({code}) online, sending msg to {account_id} at {time_part}")
                    try:
                        controller.send_message(cmd_part)
                        controller.random_delay(800, 1600)
                        controller.send_message(time_part)
                        # record last send timestamp
                        last_sent[account_id] = now

                        # Immediately attempt to verify via OCR on-screen using OCREngine helper
                        print("[*] Capturing screen to verify timestamp via OCREngine.find_channel_for_code...")
                        found, chan, raw = ocr.find_channel_for_code(code, expected_ts=time_part, retries=3, delay_s=1.0)
                        if found:
                            last_channel[account_id] = chan
                            print(f"[+] [{time_part}] OCR verification succeeded for {account_id}: channel={chan}")
                            update_dashboard(is_online=True, target_name=f"{name}{code}", target_code=code, channel_num=chan)
                        else:
                            print(f"[-] OCR verification failed for {account_id}.")
                            update_dashboard(is_online=True, target_name=f"{name}{code}", target_code=code, channel_num=None)

                    except Exception as e:
                        print(f"[!] error sending to {account_id}: {e}")
                else:
                    # still within send interval
                    pass
            else:
                # account offline — clear last_sent so next online triggers immediate send
                if account_id in last_sent:
                    print(f"[*] {code} went offline — clearing send timer")
                    last_sent.pop(account_id, None)
                if now - last >= SEND_INTERVAL:
                    update_dashboard(is_online=False, target_name=f"{name}{code}", target_code=code)


        # small sleep to avoid busy loop; main actions are scheduled above
        time.sleep(1)