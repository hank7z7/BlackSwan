import subprocess
import time
import random

# [!] Replace this with the full absolute path to adb.exe in your scrcpy folder
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


class BlueStacksController:
    def __init__(self, device_id: str | None = None):
        # if no id provided, look up connected device
        self.device_id = device_id or _get_first_device()
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
        """Send characters to the device using `input text`.

        This works most of the time but some IMEs/game clients ignore it after the
        first injection or treat it as physical keyboard input.  If typing stops
        working you can fall back to the clipboard methods below.
        """
        formatted_text = text.replace(" ", "%s")
        return self._run_adb("shell", "input", "text", formatted_text)

    def press_enter(self) -> bool:
        """Send Enter key by simulating keydown + keyup (more reliable than keyevent)."""
        print("[*] sending Enter key (keydown + keyup on KEYCODE_ENTER=66)...")
        self._run_adb("shell", "input", "keydown", "66")
        time.sleep(0.05)
        self._run_adb("shell", "input", "keyup", "66")
        print("[+] Enter key sequence sent")
        return True

    def set_clipboard(self, text: str):
        """Store a string in the emulator's clipboard using clipper broadcast.

        Requires Android 10+ or the `clipper` app.  If this fails, try
        set_clipboard_direct() instead (requires root on some BlueStacks).
        """
        success = self._run_adb("shell", "am", "broadcast", "-a", "clipper.set", "-e", "text", text, timeout=10)
        if not success:
            print("[!] clipper broadcast failed; clipboard may not be set")
        return success

    def paste_from_clipboard(self) -> bool:
        """Send the paste keyevent (KEYCODE_PASTE) to the device."""
        print("[*] pasting from clipboard (KEYCODE_PASTE 279)...")
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
        
        print(f"[*] human tap at ({tap_x}, {tap_y}) → ({end_x}, {end_y}) hold {hold_ms}ms (drift: {drift_x},{drift_y}, move: {move_x},{move_y})")
        
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

    def set_windows_clipboard(self, text: str) -> bool:
        """Set the Windows clipboard directly (more reliable than adb clipboard)."""
        try:
            ps_cmd = f'Set-Clipboard -Value @"\n{text}\n"@'
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=5, encoding='utf-8', errors='replace'
            )
            print(f"[+] Windows clipboard set: {text[:50]}...")
            return True
        except Exception as e:
            print(f"[!] Failed to set Windows clipboard: {e}")
            return False

    def send_message(self, message: str, tap_x: int | None = None, tap_y: int | None = None, send_button_x: int = 1839, send_button_y: int = 529) -> bool:
        """Send a simple message: tap → set clipboard → paste → click send button.

        Args:
            message: Text to send
            tap_x: Optional X coordinate to tap first (to focus input field)
            tap_y: Optional Y coordinate to tap first
            send_button_x: X coordinate of send button (default 1839)
            send_button_y: Y coordinate of send button (default 529)

        Returns:
            True if successful
        """
        print(f"\n[*] ==> START send_message: {message[:60]}...")
        
        # Default input coordinates (used when caller doesn't supply tap_x/tap_y)
        default_input_x = 350
        default_input_y = 313
        if tap_x is None and tap_y is None:
            tap_x = default_input_x
            tap_y = default_input_y

        if tap_x is not None and tap_y is not None:
            print(f"[1/4] Tapping input field at ({tap_x}, {tap_y})...")
            self.human_tap(tap_x, tap_y)
            self.random_delay(400, 800)
            print("[+] Input field tapped")

        print("[2/5] Setting Windows clipboard...")
        self.set_windows_clipboard(message)
        self.random_delay(200, 400)
        print("[+] Clipboard set")

        print("[3/5] Pasting message...")
        self.paste_from_clipboard()
        self.random_delay(300, 600)
        print("[+] Paste sent")

        # instead of tapping the send button, press enter in the input field
        print("[4/5] Pressing Enter to send message...")
        self.human_tap(send_button_x, send_button_y)
        self.random_delay(500, 1000)
        print("[+] Enter pressed, message should be sent")

        print("[5/5] Message sent\n")
        return True


if __name__ == "__main__":
    import time

    # 1. Initialize controller (auto-detect device from adb devices)
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