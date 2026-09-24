import ctypes
from ctypes import wintypes
import time

user32 = ctypes.windll.user32

def get_window_text(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length > 0:
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        return buff.value
    return ""

def find_codex_window():
    found = []
    def enum_cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            title = get_window_text(hwnd)
            if "codex" in title.lower():
                found.append(hwnd)
        return True
    
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(EnumWindowsProc(enum_cb), 0)
    return found

def inspect_window_hierarchy(hwnd, depth=0):
    indent = "  " * depth
    title = get_window_text(hwnd)
    print(f"{indent}HWND: {hwnd}, Title: {title}")
    
    def enum_child_cb(child_hwnd, lparam):
        inspect_window_hierarchy(child_hwnd, depth + 1)
        return True
    
    EnumChildProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumChildWindows(hwnd, EnumChildProc(enum_child_cb), 0)

if __name__ == "__main__":
    hwnds = find_codex_window()
    if not hwnds:
        print("CodeX window not found.")
    for h in hwnds:
        print(f"\n--- Hierarchy for HWND {h} ---")
        inspect_window_hierarchy(h)
