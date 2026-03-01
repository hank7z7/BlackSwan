import subprocess
import time
import random
import sys
import ctypes

# Ensure console output uses UTF-8 on Windows terminals
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# [!] Replace this with the full absolute path to adb.exe in your scrcpy folder
ADB_PATH = r"C:\Users\ghank\scrcpy-win64-v3.3.4\scrcpy-win64-v3.3.4\adb.exe"


class BlueStacksController:
    def __init__(self, device_id: str | None = None, adb_address: str | None = None):
        """Initialize controller.

        Args:
            device_id: Optional explicit adb device id (example: 'emulator-5554' or '127.0.0.1:5555').
            adb_address: Optional adb TCP address to connect to (example: '127.0.0.1:5555').

        If `adb_address` is provided we attempt `adb connect <adb_address>` and use
        that address as the device id. If neither is provided we auto-detect the
        first available device from `adb devices`.
        """
        # If an adb TCP address was provided, try to connect and use it
        if adb_address:
            print(f"[*] attempting adb connect to {adb_address}...")
            try:
                subprocess.run([ADB_PATH, "connect", adb_address], capture_output=True, text=True, timeout=5)
            except Exception as e:
                print(f"[!] adb connect failed: {e}")
            # prefer explicit device_id if given, otherwise use the adb_address
            self.device_id = device_id or adb_address
        else:
            # if no id provided, default to emulator-5554
            self.device_id = device_id or "emulator-5554"

        if not self.device_id:
            raise RuntimeError("no ADB device found; make sure emulator is running and adb devices lists it")
        print(f"[*] using device {self.device_id}")

    def _run_adb(self, *args, timeout: int = 5) -> bool:
        """Run an adb command and return True if successful, False otherwise.

        Captures stdout/stderr and prints for debugging.
        """
        cmd = [ADB_PATH, "-s", self.device_id] + list(args)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace')
            if result.returncode != 0:
                print(f"[!] adb error: {' '.join(cmd)}")
                print(f"    stderr: {result.stderr}")
                return False
            if result.stdout:
                print(f"[+] {result.stdout.strip()}")
            return True
        except subprocess.TimeoutExpired:
            print(f"[!] adb timeout on: {' '.join(cmd)}")
            return False
        except Exception as e:
            print(f"[!] adb exception: {e}")
            return False

    def test_connection(self) -> bool:
        """Test if the device is responsive."""
        print(f"[*] testing connection to {self.device_id}...")
        return self._run_adb("shell", "echo", "ok")

    def tap(self, x: int, y: int):
        return self._run_adb("shell", "input", "tap", str(x), str(y))

    def type_text(self, text: str):
        # Use Windows clipboard API directly (handles Chinese/Unicode correctly)
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        k32.GlobalAlloc.restype = ctypes.c_size_t
        k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = [ctypes.c_size_t]
        k32.GlobalUnlock.argtypes = [ctypes.c_size_t]
        u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        try:
            data = (text + '\0').encode('utf-16-le')
            handle = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not handle:
                raise RuntimeError("GlobalAlloc failed")
            ptr = k32.GlobalLock(handle)
            if not ptr:
                raise RuntimeError("GlobalLock failed")
            ctypes.memmove(ptr, data, len(data))
            k32.GlobalUnlock(handle)
            u32.OpenClipboard(0)
            u32.EmptyClipboard()
            u32.SetClipboardData(CF_UNICODETEXT, handle)
            u32.CloseClipboard()
        except Exception as e:
            print(f"[!] Failed to set clipboard: {e}")
            return False
        time.sleep(0.3)
        return self._run_adb("shell", "input", "keyevent", "279")

    def raw_shell_command(self, *cmd_parts) -> bool:
        """Run a raw adb shell command for testing/debugging."""
        return self._run_adb("shell", *cmd_parts)

    def random_delay(self, min_ms: float = 300, max_ms: float = 800) -> None:
        """Sleep for a random duration to simulate human behavior.
        
        Args:
            min_ms: Minimum delay in milliseconds (default 300)
            max_ms: Maximum delay in milliseconds (default 800)
        """
        delay_seconds = random.uniform(min_ms, max_ms) / 1000.0
        time.sleep(delay_seconds)

    def human_tap(self, x: int, y: int, hold_min_ms: int = 50, hold_max_ms: int = 150) -> bool:
        """Perform a human-like tap with random duration and small movement during hold.
        
        Simulates a realistic touch by:
        - Adding small random drift to starting position (±5 pixels)
        - Moving slightly while holding (±3 pixels) like hand tremor
        - Holding for a variable duration
        
        Args:
            x: X coordinate
            y: Y coordinate
            hold_min_ms: Minimum hold duration in milliseconds
            hold_max_ms: Maximum hold duration in milliseconds
            
        Returns:
            True if successful
        """
        # Add small random drift to starting position (±5 pixels)
        drift_x = random.randint(-5, 5)
        drift_y = random.randint(-5, 5)
        tap_x = x + drift_x
        tap_y = y + drift_y
        
        # Add small movement during hold (hand tremor ±3 pixels)
        move_x = random.randint(-3, 3)
        move_y = random.randint(-3, 3)
        end_x = tap_x + move_x
        end_y = tap_y + move_y
        
        # Random hold duration
        hold_ms = random.randint(hold_min_ms, hold_max_ms)
        
        print(f"[*] human tap at ({tap_x}, {tap_y}) to ({end_x}, {end_y}) hold {hold_ms}ms (drift: {drift_x},{drift_y}, move: {move_x},{move_y})")
        
        # Use swipe to simulate tap with movement while holding
        self._run_adb("shell", "input", "touchscreen", "swipe", str(tap_x), str(tap_y), str(end_x), str(end_y), str(hold_ms))
        return True

    def test_keyboard_input(self):
        """Send individual keystrokes to test if input works at all."""
        print("[*] testing keyboard input: sending 'a' 'b' 'c'...")
        self._run_adb("shell", "input", "text", "a")
        time.sleep(0.1)
        self._run_adb("shell", "input", "text", "b")
        time.sleep(0.1)
        self._run_adb("shell", "input", "text", "c")
        print("[*] if you see 'abc' in the focused field, keyboard input works")

    def send_message(self, message: str, tap_x: int | None = None, tap_y: int | None = None, send_button_x: int = 1839, send_button_y: int = 529) -> bool:
        """Send a message: tap input field → type text → click send button.

        Args:
            message: Text to send
            tap_x: Optional X coordinate to tap first (to focus input field)
            tap_y: Optional Y coordinate to tap first
            send_button_x: X coordinate of send button (default 1839)
            send_button_y: Y coordinate of send button (default 529)

        Returns:
            True if successful
        """
        print(f"\n[*] ==> START send_message")
        
        # Default input coordinates (used when caller doesn't supply tap_x/tap_y)
        default_input_x = 350
        default_input_y = 313
        if tap_x is None and tap_y is None:
            tap_x = default_input_x
            tap_y = default_input_y

        if tap_x is not None and tap_y is not None:
            self.human_tap(tap_x, tap_y)
            self.random_delay(400, 800)
            # print("[+] Input field tapped")

        self.type_text(message)

        # instead of tapping the send button, press enter in the input field
        # print("[4/5] Pressing Enter to send message...")
        self.human_tap(send_button_x, send_button_y)
        self.random_delay(500, 1000)
        return True


if __name__ == "__main__":
    # 1. Initialize controller (defaults to emulator-5554)
    controller = BlueStacksController()

    # 1.5 Test connection
    print("\n[*] Testing ADB connection...")
    if not controller.test_connection():
        print("[!] Connection failed! Make sure BlueStacks is running")
        exit(1)
    print("[+] Connection successful!\n")

    # 2. Check Android version
    print("[*] Checking Android version...")
    controller.raw_shell_command("getprop", "ro.build.version.release")

    print("\n[*] Wait 5 seconds to switch to game window and open chat...")
    time.sleep(5)

    # 3. Send first message
    print("\n[=== Sending Message 1 ===]")
    controller.send_message("/w 漢娜醬晚餐吃筍絲弩肉飯#00TPK")
    time.sleep(1)
    controller.send_message("hello world 1")
    time.sleep(5)
    
    # 4. Send second message (no need to kill-server)
    print("\n[=== Sending Message 2 ===]")
    controller.send_message("/w 漢娜醬晚餐吃筍絲弩肉飯#00TPK")
    time.sleep(1)
    controller.send_message("hello world 2")
    time.sleep(5)

    # 5. Send third message
    print("\n[=== Sending Message 3 ===]")
    controller.send_message("/w 漢娜醬晚餐吃筍絲弩肉飯#00TPK")
    time.sleep(1)
    controller.send_message("hello world 3")
    time.sleep(5)

    print("\n[+] All messages sent!")