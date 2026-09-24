#!/usr/bin/env python3
"""
Standalone Auto-Accept Background Service
==========================================
Runs 24/7 in a terminal to automatically click "Allow/Run/Confirm" blue buttons
in Antigravity (and other AI editors) without needing the full GUI.

USAGE:
    python auto_accept.py
    python auto_accept.py --editor windsurf
    python auto_accept.py --interval 2.0

STOP:
    Press Ctrl+C in the terminal to stop.
"""

import ctypes
import sys
import time
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────

EDITOR_KEYWORDS = {
    "antigravity": ["Antigravity", "antigravity"],
    "windsurf":    ["Windsurf", "windsurf"],
    "windsurf_next": ["Windsurf Next", "windsurf-next"],
    "cursor":      ["Cursor", "cursor"],
    "vscode":      ["Visual Studio Code", "vscode", "VS Code"],
}

VK_MAP = {
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12,
    "enter": 0x0D, "tab": 0x09, "escape": 0x1B,
    "space": 0x20, "backspace": 0x08,
}
for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
    VK_MAP[c.lower()] = ord(c.upper())
for d in "0123456789":
    VK_MAP[d] = ord(d)

KEYEVENTF_KEYUP = 0x0002


# ─────────────────────────────────────────────────────
# CORE LOGIC
# ─────────────────────────────────────────────────────

def find_editor_window(editor: str) -> int:
    """Enumerate all top-level windows and return handle for the editor."""
    from ctypes import wintypes
    user32 = ctypes.windll.user32

    search_terms = EDITOR_KEYWORDS.get(editor, [])
    if not search_terms:
        return None

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found = [None]

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                for term in search_terms:
                    if term.lower() in title.lower():
                        found[0] = hwnd
                        return False
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return found[0]


def force_focus(hwnd: int) -> bool:
    """Forcefully focus a window using AttachThreadInput trick."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    try:
        if not user32.IsWindowVisible(hwnd):
            return False

        foreground = user32.GetForegroundWindow()
        if foreground == hwnd:
            return True  # already focused

        fore_tid = user32.GetWindowThreadProcessId(foreground, None)
        this_tid = kernel32.GetCurrentThreadId()

        user32.AttachThreadInput(this_tid, fore_tid, True)
        user32.ShowWindow(hwnd, 5)       # SW_SHOW
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.AttachThreadInput(this_tid, fore_tid, False)
        return True
    except Exception as e:
        logger.debug(f"Focus fallback: {e}")
        try:
            user32.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False


def press_hotkey(hotkey: str):
    """Simulate a keyboard shortcut (e.g., 'alt+enter')."""
    user32 = ctypes.windll.user32
    keys = [k.strip().lower() for k in hotkey.split("+")]
    vk_codes = [VK_MAP.get(k, 0) for k in keys]

    # Press all down
    for vk in vk_codes:
        if vk:
            user32.keybd_event(vk, 0, 0, 0)

    time.sleep(0.06)  # hold briefly

    # Release all in reverse
    for vk in reversed(vk_codes):
        if vk:
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def pulse_allow_buttons():
    """Send all common 'Accept / Allow / Run' shortcuts to the focused editor."""
    # PRIMARY: Antigravity's "Run Alt+↵" button
    press_hotkey("alt+enter")
    time.sleep(0.04)

    # SECONDARY: "Always run" (Alt+A or Alt+L)
    press_hotkey("alt+a")
    time.sleep(0.04)
    press_hotkey("alt+l")
    time.sleep(0.04)

    # TERTIARY: Run, Confirm, Yes, Retry
    press_hotkey("alt+r")
    time.sleep(0.04)
    press_hotkey("alt+c")
    time.sleep(0.04)
    press_hotkey("alt+y")
    time.sleep(0.04)

    # FALLBACKS: Plain Enter and Ctrl+Enter
    press_hotkey("enter")
    time.sleep(0.04)
    press_hotkey("ctrl+enter")


# ─────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────

def run_loop(editor: str, interval: float, verbose: bool):
    logger.info(f"🟢 Auto-Accept running | Editor: {editor} | Interval: {interval}s")
    logger.info("   Press Ctrl+C to stop.\n")

    last_hwnd = None
    missed = 0

    while True:
        try:
            hwnd = find_editor_window(editor)

            if hwnd is None:
                if missed % 10 == 0:
                    logger.warning(f"⚠️  Cannot find '{editor}' window. Is it open?")
                missed += 1
                time.sleep(interval)
                continue

            missed = 0

            if hwnd != last_hwnd:
                logger.info(f"✅  Found {editor} window (HWND: {hwnd})")
                last_hwnd = hwnd

            focused = force_focus(hwnd)

            if focused:
                pulse_allow_buttons()
                if verbose:
                    logger.info(f"   ↳ Pulsed accept buttons for HWND {hwnd}")
            else:
                if verbose:
                    logger.info(f"   ↳ Could not focus HWND {hwnd}, skipping pulse")

        except KeyboardInterrupt:
            logger.info("\n🛑 Stopped by user.")
            break
        except Exception as e:
            logger.error(f"Error in loop: {e}")

        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(
        description="Auto-Accept: auto-click 'Allow / Run / Confirm' in AI editors"
    )
    parser.add_argument(
        "--editor", default="antigravity",
        choices=list(EDITOR_KEYWORDS.keys()),
        help="Which editor to target (default: antigravity)"
    )
    parser.add_argument(
        "--interval", type=float, default=2.0,
        help="Seconds between each pulse (default: 2.0)"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print every pulse to the console"
    )

    args = parser.parse_args()
    run_loop(args.editor, args.interval, args.verbose)


if __name__ == "__main__":
    main()
