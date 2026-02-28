import subprocess
import cv2
import numpy as np
import pytesseract
import time
import re
import os
import sys
import unicodedata

# Ensure console output uses UTF-8 on Windows terminals
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# [!] Point to the Tesseract executable installed by winget
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# [!] Replace with your scrcpy adb path
ADB_PATH = r"C:\Users\ghank\scrcpy-win64-v3.3.4\scrcpy-win64-v3.3.4\adb.exe" 

def _get_first_device() -> str | None:
    """Return the first non-empty device id from `adb devices` output."""
    proc = subprocess.run([ADB_PATH, "devices"], capture_output=True, text=True, encoding='utf-8', errors='replace')
    lines = proc.stdout.strip().splitlines()
    # first line is header
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return parts[0]
    return None

class OCREngine:
    def __init__(self, adb_address: str | None = None, device_id: str | None = None):
        """Initialize OCR engine with optional adb address or device id.

        Args:
            adb_address: optional TCP address to `adb connect` (e.g. '127.0.0.1:5555')
            device_id: optional explicit device id to use for `-s` (overrides adb_address)
        """
        self.adb_address = adb_address
        # if an explicit device_id was provided prefer it
        self.device_id = device_id or adb_address
        if adb_address and not device_id:
            # try to connect to the adb tcp address; ignore failure (we'll try anyway)
            try:
                print(f"[*] attempting adb connect to {adb_address}...")
                res = subprocess.run([ADB_PATH, "connect", adb_address], capture_output=True, text=True, timeout=5)
                if res.stdout:
                    print(f"[+] adb connect stdout: {res.stdout.strip()}")
                if res.stderr:
                    print(f"[!] adb connect stderr: {res.stderr.strip()}")
            except Exception as e:
                print(f"[!] adb connect exception: {e}")

    def capture_screen(self):
        """Capture the emulator screen directly into memory using ADB"""
        print("[*] Capturing screen via ADB...")
        # try running adb exec-out; prefer using -s <device> when available
        def run_screencap(cmd):
            try:
                res = subprocess.run(cmd, capture_output=True, timeout=15)
                return res
            except Exception as e:
                print(f"[!] adb screencap exec failed: {e}")
                return None

        if self.device_id:
            cmd = [ADB_PATH, "-s", self.device_id, "exec-out", "screencap", "-p"]
        else:
            cmd = [ADB_PATH, "exec-out", "screencap", "-p"]

        res = run_screencap(cmd)
        if res is None:
            return None

        # If adb returned an error, show stderr and attempt to recover when possible
        stderr = (res.stderr.decode("utf-8", errors="replace") if res.stderr else "")
        if res.returncode != 0 or not res.stdout:
            if stderr:
                print(f"[!] adb error: {stderr.strip()}")
            else:
                print("[!] adb screencap produced no output")

            # common case: "more than one device/emulator" -> try auto-selecting first device
            if "more than one device" in stderr.lower() or "more than one" in stderr.lower():
                dev = _get_first_device()
                if dev:
                    print(f"[*] Multiple devices present; retrying with first device: {dev}")
                    self.device_id = dev
                    cmd = [ADB_PATH, "-s", self.device_id, "exec-out", "screencap", "-p"]
                    res = run_screencap(cmd)
                    if res is None or res.returncode != 0 or not res.stdout:
                        err2 = (res.stderr.decode("utf-8", errors="replace") if res and res.stderr else "")
                        print(f"[!] retry failed: {err2}")
                        return None
                else:
                    print("[!] no device found to retry with")
                    return None
            else:
                return None

        image_bytes = res.stdout
        if not image_bytes:
            print("[-] exec-out produced no bytes. Capture failed.")
            return None

        # Convert raw bytes to OpenCV image format (BGR)
        image_array = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        return img

    def isolate_bright_green_text(self, bgr_img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Isolate bright green text from a BGR image.

        Returns a tuple `(colored_result, gray_for_ocr)` where `colored_result` keeps
        the original color for green pixels and black elsewhere, and `gray_for_ocr`
        is a grayscale image suitable for OCR (non-green pixels darkened).
        """
        if bgr_img is None:
            return None, None

        hsv_img = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)

        # Tuned range for bright green; adjust if necessary
        # Make the bound tighter to avoid picking up non-green artifacts; we can rely on the timestamp format to filter further
        lower_green = np.array([50, 100, 100])
        upper_green = np.array([75, 255, 255])

        mask = cv2.inRange(hsv_img, lower_green, upper_green)

        # Morphological cleanup
        kernel = np.ones((2, 2), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        # Colored result: keep original green-colored pixels, black elsewhere
        colored = cv2.bitwise_and(bgr_img, bgr_img, mask=mask)

        # Prepare grayscale for OCR: convert colored to gray, and boost contrast locally via CLAHE
        gray_colored = cv2.cvtColor(colored, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_for_ocr = clahe.apply(gray_colored)

        return colored, gray_for_ocr

    def parse_whisper_info(self, text: str, expected_code: str | None = None, expected_ts: str | None = None) -> tuple[bool, str | None, str | None]:
        """
        Parse OCR text to extract the channel number and validate code & timestamp.
        Pattern expected: ... #{code}[頻道.{channel_num}]<<{timestamp}
        
        Returns:
            (is_valid: bool, channel_num: str | None, timestamp: str | None)
        """
        if not text:
            return False, None, None
            
        
        # 正規化：移除所有空白字元，減少 OCR 空格造成的誤判
        norm = re.sub(r"\s+", "", text)
        # 轉為半形，統一全形括號和其他符號
        norm = unicodedata.normalize("NFKC", norm)
        print(f"[DEBUG] OCR normalized text: {norm}")

        # 2. Regex specifically tailored to your observation:
        # #(?P<code>.{5})       : Match '#' and capture exactly 5 characters after it
        # .*?                   : Non-greedy match for the garbage text in between
        # (?P<channel>\d+)      : Capture the channel numbers
        # .                     : Skip exactly ONE character (the OCR'd bracket)
        # <<                    : The absolute anchor "<<"
        # (?P<ts>\d{8})         : Capture exactly 8 digits as timestamp
        
        pattern = r"#(?P<code>.{5}).*?(?P<channel>\d+).<<(?P<ts>\d{8})"
        match = re.search(pattern, norm)

        if not match:
            print("[DEBUG] Regex match failed. The string structure is too broken.")
            return False, None, None
        
        # parsed_code keep # prefix
        parsed_code = ('#') + match.group("code")
        channel_num = match.group("channel")
        parsed_ts = match.group("ts")
        
        print(f"[DEBUG] Parsed - Code: {parsed_code}, Channel: {channel_num}, Timestamp: {parsed_ts}")

        # 驗證 Code 是否符合預期
        if expected_code and parsed_code != expected_code:
            print(f"[DEBUG] ❌ Code mismatch. Expected: {expected_code}, Got: {parsed_code}")
            return False, channel_num, parsed_ts
            
        # 驗證 Timestamp 是否符合預期
        if expected_ts and parsed_ts != expected_ts:
            print(f"[DEBUG] ❌ Timestamp mismatch. Expected: {expected_ts}, Got: {parsed_ts}")
            return False, channel_num, parsed_ts
            
        print("[DEBUG] ✅ Match successful!")
        return True, channel_num, parsed_ts

    def find_channel_for_code(self, code: str, expected_ts: str | None = None, retries: int = 3, delay_s: float = 1.0) -> tuple[bool, str | None, str]:
        """Capture screen, OCR and attempt to find channel for a given `code` and timestamp.

        Returns (found: bool, channel_or_None, raw_ocr_text).
        """
        last_raw = ""
        custom_config = r'-l chi_tra+eng --oem 3 --psm 6'

        for attempt in range(1, retries + 1):
            img = self.capture_screen()
            if img is None:
                return False, None, ""

            # Crop to same ROI as extract_chat_info
            h, w = img.shape[:2]
            y1, y2, x1, x2 = 219, 260, 291, 890
            y1 = max(0, min(y1, h - 1))
            y2 = max(0, min(y2, h))
            x1 = max(0, min(x1, w - 1))
            x2 = max(0, min(x2, w))
            cropped = img[y1:y2, x1:x2] if (y2 > y1 and x2 > x1) else img

            # isolate green text
            _, gray_iso = self.isolate_bright_green_text(cropped)
            if gray_iso is None:
                gray_iso = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)

            # Binarize for clearer OCR
            _, bw = cv2.threshold(gray_iso, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # save debug OCR images for the first attempt
            if attempt == 1:
                cv2.imwrite("debug_cropped.png", cropped)
                cv2.imwrite("debug_gray_iso.png", gray_iso)
                cv2.imwrite("debug_bw.png", bw)
                print("[+] Saved debug images: debug_cropped.png, debug_gray_iso.png, debug_bw.png")

            # OCR
            raw = pytesseract.image_to_string(bw, config=custom_config)

            found, channel, ts = self.parse_whisper_info(raw, expected_code=code, expected_ts=expected_ts)
            if found:
                return True, channel, raw
            time.sleep(delay_s)

        return False, None, last_raw

if __name__ == "__main__":
    engine = OCREngine(adb_address="127.0.0.1:5555")
    
    # 1. Take a screenshot
    screen_img = engine.capture_screen()
    
    if screen_img is not None:
        # 2. Save a debug copy to your PC so you can open it in Paint 
        # to find the exact Y and X coordinates for cropping
        cv2.imwrite("debug_full_screen.png", screen_img)
        print("[+] Saved 'debug_full_screen.png'. Open this file to find your chat box coordinates!")
        
        # 3. Test OCR output
        start_time = time.time()
        raw_text = engine.extract_chat_info(screen_img)
        end_time = time.time()
        
        print("\n=== OCR RAW OUTPUT ===")
        print(raw_text)
        print("======================")
        print(f"[i] OCR took {end_time - start_time:.2f} seconds.")