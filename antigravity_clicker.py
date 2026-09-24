import pyautogui
import time
import sys
import numpy as np
from PIL import Image

# Improved Color Range for VS Code / Cursor / Windsurf Blue
# Handles typical blue variations, including highlights/hover.
BLUE_MIN = np.array([0, 70, 140])
BLUE_MAX = np.array([60, 170, 255])

DEBUG_MODE = True # Set to True to save masks for debugging

import cv2

def find_candidate_buttons():
    """Scans the screen for blue regions and returns their centers using OpenCV."""
    screen = pyautogui.screenshot()
    width, height = screen.size
    img_np = np.array(screen)
    
    # Focus on the right half of the screen
    right_half_start = width // 2
    img_np_right = img_np[:, right_half_start:, :]
    
    # Create mask (OpenCV uses BGR, but PIL/PyAutoGUI use RGB)
    # img_np_right is RGB
    mask = cv2.inRange(img_np_right, BLUE_MIN, BLUE_MAX)
    
    if DEBUG_MODE:
        cv2.imwrite("debug_mask_cv2.png", mask)

    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    buttons = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w > 40 and h > 10 and w < 300 and h < 80:
            # Check if it's solid-ish (not just a line)
            area = cv2.contourArea(cnt)
            if area > 400: # w*h/2 roughly
                buttons.append((right_half_start + x + w//2, y + h//2))
    
    return buttons

def main():
    print("=== Antigravity Terminal Auto-Clicker V2.3 ===")
    print("Detecting buttons: 'Run', 'Allow', 'Retry', 'Accept', etc.")
    print("Press Ctrl+C to stop.")
    
    # Disable Fail-Safe if it causes issues, but keep it for safety if possible
    # pyautogui.FAILSAFE = False 

    try:
        while True:
            try:
                candidates = find_candidate_buttons()
                if candidates:
                    print(f"[{time.strftime('%H:%M:%S')}] Detected {len(candidates)} button(s).")
                    
                    # Scroll down to ensure the latest command is visible
                    try:
                        pyautogui.scroll(-500) # Negative for scrolling down
                        time.sleep(0.2)
                    except: pass
                    
                    # Keyboard shortcut
                    try:
                        pyautogui.hotkey('win', 'alt', 'enter') # Try different variations
                        pyautogui.hotkey('ctrl', 'enter')
                        pyautogui.hotkey('alt', 'enter')
                    except: pass
                    
                    # Click fallback
                    for pos in candidates:
                        try:
                            pyautogui.click(pos[0], pos[1])
                            print(f"Clicked at {pos}")
                        except: pass
                    
                    time.sleep(3)
            except Exception as e:
                print(f"Loop error: {e}")
                time.sleep(1)
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopped.")
    except pyautogui.FailSafeException:
        print("\nFail-safe triggered (Mouse in corner).")
    except Exception as e:
        print(f"\nFatal: {e}")

if __name__ == "__main__":
    main()
