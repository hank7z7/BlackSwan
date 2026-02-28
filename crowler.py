from playwright.sync_api import sync_playwright
import time

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


def check_multiple_status(urls: list[str], max_workers: int = 5) -> dict[str, dict]:
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


if __name__ == "__main__":
    # list of targets to check
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
    ]

    statuses = check_multiple_status(targets, max_workers=5)
    for url, info in statuses.items():
        state = "ONLINE" if info.get("online") else "OFFLINE"
        name = info.get("name") or "<unknown>"
        code = info.get("code") or "<unknown>"
        print(f"{url}  |  name={name}  code={code}  --> {state}")
    # You can test this right now in your terminal!