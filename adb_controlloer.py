import subprocess
import time

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

    def press_enter(self):
        return self._run_adb("shell", "input", "keyevent", "66")

    def set_clipboard(self, text: str):
        """Store a string in the emulator's clipboard using clipper broadcast.

        Requires Android 10+ or the `clipper` app.  If this fails, try
        set_clipboard_direct() instead (requires root on some BlueStacks).
        """
        success = self._run_adb("shell", "am", "broadcast", "-a", "clipper.set", "-e", "text", text, timeout=10)
        if not success:
            print("[!] clipper broadcast failed; clipboard may not be set")
        return success

    def paste_from_clipboard(self):
        """Send the paste keyevent (KEYCODE_PASTE) to the device."""
        return self._run_adb("shell", "input", "keyevent", "279")

    def raw_shell_command(self, *cmd_parts) -> bool:
        """Run a raw adb shell command for testing/debugging."""
        return self._run_adb("shell", *cmd_parts)

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

    def clear_input_field(self) -> bool:
        """Clear the currently focused input field (Ctrl+A, then Delete)."""
        print("[*] clearing input field...")
        self._run_adb("shell", "input", "keyevent", "29")  # Ctrl+A
        time.sleep(0.1)
        self._run_adb("shell", "input", "keyevent", "67")  # KEYCODE_DEL
        time.sleep(0.1)
        return True

    def send_message(self, message: str, tap_x: int | None = None, tap_y: int | None = None) -> bool:
        """High-level method: tap (optional) → set clipboard → paste → enter.

        Args:
            message: Text to send
            tap_x: Optional X coordinate to tap first (to focus input field)
            tap_y: Optional Y coordinate to tap first

        Returns:
            True if successful
        """
        if tap_x is not None and tap_y is not None:
            print(f"[*] tapping ({tap_x}, {tap_y}) to focus input field...")
            self.tap(tap_x, tap_y)
            time.sleep(0.5)

        self.set_windows_clipboard(message)
        time.sleep(0.2)

        print("[*] pasting message...")
        self.paste_from_clipboard()
        time.sleep(0.3)

        print("[*] sending message (Enter)...")
        self.press_enter()
        time.sleep(0.3)

        print("[+] message sent!\n")
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

    print("\n[*] Wait 2 seconds to switch to game window and open chat...")
    time.sleep(2)

    TEST_X = 350
    TEST_Y = 313

    # 3. Send first message
    print("\n[=== Sending Message 1 ===]")
    controller.send_message("/w 芭蕾玲娜#aHe5L hello world 1", TEST_X, TEST_Y)
    time.sleep(1)

    # 4. Send second message (no need to kill-server)
    print("\n[=== Sending Message 2 ===]")
    controller.send_message("/w 芭蕾玲娜#aHe5L hello world 2", TEST_X, TEST_Y)
    time.sleep(1)

    # 5. Send third message
    print("\n[=== Sending Message 3 ===]")
    controller.send_message("/w 芭蕾玲娜#aHe5L hello world 3", TEST_X, TEST_Y)
    time.sleep(1)

    print("\n[+] All messages sent!")