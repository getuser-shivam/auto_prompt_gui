#!/usr/bin/env python3
"""
Antigravity Auto-Retry & Command Approval Clicker
=================================================
Automatically handles:
1. "Agent terminated due to error" card (by clicking the blue "Retry" button).
2. "Allow running this command?" modal prompt (by selecting Option 3: "Yes, and always allow..." and clicking "Submit").

Usage:
    python antigravity_retry_clicker.py
    python antigravity_retry_clicker.py --dry-run
    python antigravity_retry_clicker.py --test-image path/to/image.png
"""

import os
import sys
import time
import json
import math
import argparse
import subprocess
import logging
import pyautogui
import numpy as np
import cv2
from PIL import Image

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# Improved Color Range for VS Code / Cursor / Windsurf Blue
# Handles typical blue variations, including highlights/hover and dialog buttons.
# `#007acc` (editor buttons) -> R=0, G=122, B=204
# `#4d78cc` (dialog buttons) -> R=77, G=120, B=204
BLUE_MIN = np.array([0, 60, 120])
BLUE_MAX = np.array([100, 180, 255])

def run_ocr(ocr_script_path, image_path=""):
    """Runs the PowerShell OCR helper script and returns parsed JSON results."""
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", ocr_script_path
    ]
    if image_path:
        cmd.append(image_path)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        logger.error(f"PowerShell OCR script failed: {e.stderr}")
        return {"status": "error", "message": e.stderr}
    except Exception as e:
        logger.error(f"Error running OCR: {e}")
        return {"status": "error", "message": str(e)}

def find_blue_buttons(image_path=None):
    """
    Scans the screen or an image for blue button regions using OpenCV.
    Returns a list of dicts: [{'center': (x, y), 'box': (x, y, w, h)}]
    """
    try:
        if image_path:
            img = Image.open(image_path)
        else:
            img = pyautogui.screenshot()
            
        img_np = np.array(img)
        # Handle RGBA to RGB conversion if needed
        if img_np.shape[2] == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2RGB)
            
        mask = cv2.inRange(img_np, BLUE_MIN, BLUE_MAX)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        buttons = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            # Relaxed dimension limits for the button (accommodating small/large sizes)
            if w >= 20 and h >= 10 and w <= 300 and h <= 80:
                area = cv2.contourArea(cnt)
                if area > 100: # Solid region filter
                    buttons.append({
                        'center': (x + w // 2, y + h // 2),
                        'box': (x, y, w, h)
                    })
        return buttons
    except Exception as e:
        logger.error(f"Error in OpenCV button detection: {e}")
        return []

def get_dialog_bounds(lines, keywords):
    """Computes the padded bounding box of the dialog based on matching OCR lines."""
    matching_lines = []
    for line in lines:
        text = line.get("text", "").lower()
        for kw in keywords:
            if kw in text:
                matching_lines.append(line)
                break
                
    if not matching_lines:
        return None
        
    coords = []
    for l in matching_lines:
        for w in l.get("words", []):
            coords.append((w["x"], w["y"], w["w"], w["h"]))
            
    if not coords:
        return None
        
    min_x = min(c[0] for c in coords)
    max_x = max(c[0] + c[2] for c in coords)
    min_y = min(c[1] for c in coords)
    max_y = max(c[1] + c[3] for c in coords)
    
    # Pad the bounding box to fully encompass the buttons
    return {
        "min_x": min_x - 60,
        "max_x": max_x + 180,
        "min_y": min_y - 40,
        "max_y": max_y + 100
    }

def process_detection(ocr_data, image_path, dry_run=False):
    """
    Parses OCR results, detects state, handles errors/commands accordingly.
    """
    if ocr_data.get("status") != "success":
        logger.warning(f"OCR failed: {ocr_data.get('message')}")
        return False

    lines = ocr_data.get("lines", [])
    
    # Check A: Command execution permission dialog
    command_keywords = [
        "allow running this command", 
        "allow running this", 
        "yes, allow this time", 
        "yes, and always allow", 
        "no (tell",
        "skip"
    ]
    command_bounds = get_dialog_bounds(lines, command_keywords)
            
    if command_bounds:
        logger.info("Command execution permission prompt detected on screen!")
        # Find Option 3 text: "Yes, and always allow" (must exclude Option 2 containing "in" or "project")
        option_3_coord = None
        option_3_candidates = []
        for line in lines:
            text = line.get("text", "").lower()
            if "yes, and always allow" in text:
                words_list = text.split()
                # Option 2 contains "in" and "project". Option 3 has neither.
                if "in" in words_list or "project" in words_list:
                    continue
                words = line.get("words", [])
                if words:
                    option_3_candidates.append(line)
        
        if option_3_candidates:
            # If multiple matches, pick the one lowest on screen (largest Y coordinate)
            best_line = max(option_3_candidates, key=lambda l: l["words"][0]["y"])
            words = best_line.get("words", [])
            line_x = words[0]["x"]
            line_y = words[0]["y"]
            # Target Option 3 text area
            option_3_coord = (line_x + 60, line_y + 6)
            logger.info(f"Found Option 3 ('Yes, and always allow') at coordinate {option_3_coord} (Line text: '{best_line.get('text')}', Y={line_y})")
                    
        # Find the blue "Submit" button
        blue_buttons = find_blue_buttons(image_path)
        submit_button = None
        
        # Enforce spatial constraint: Submit button must be inside the dialog bounding box
        valid_buttons = []
        for btn in blue_buttons:
            bx, by = btn['center']
            if (command_bounds["min_x"] <= bx <= command_bounds["max_x"]) and (command_bounds["min_y"] <= by <= command_bounds["max_y"]):
                # Also ensure it's below Option 3 if we found it
                if option_3_coord and by <= option_3_coord[1]:
                    continue
                valid_buttons.append(btn)
        
        if valid_buttons:
            # Pick the button closest to bottom-right of the dialog
            submit_button = max(valid_buttons, key=lambda b: b['center'][0] + b['center'][1])
                
        if option_3_coord and submit_button:
            cx, cy = submit_button['center']
            logger.info(f"SUCCESS: Target blue 'Submit' button identified at coordinate ({cx}, {cy})")
            
            if dry_run:
                logger.info(f"[DRY RUN] Would click Option 3 at {option_3_coord} and Submit at ({cx}, {cy})")
                try:
                    if image_path:
                        img = Image.open(image_path)
                    else:
                        img = pyautogui.screenshot()
                    
                    img_np = np.array(img)
                    # Draw Option 3 highlight
                    cv2.circle(img_np, option_3_coord, 8, (0, 255, 0), -1)
                    
                    # Draw Submit button highlight
                    x, y, w, h = submit_button['box']
                    cv2.rectangle(img_np, (x, y), (x + w, y + h), (0, 0, 255), 2)
                    cv2.circle(img_np, (cx, cy), 5, (0, 0, 255), -1)
                    
                    if img_np.shape[2] == 4:
                        img_out = Image.fromarray(img_np, 'RGBA')
                    else:
                        img_out = Image.fromarray(img_np, 'RGB')
                    img_out.save("debug_click.png")
                    logger.info("Saved debug detection visualization to debug_click.png")
                except Exception as draw_err:
                    logger.error(f"Could not draw debug image: {draw_err}")
                return True
            else:
                logger.info(f"CLICKING: Clicking Option 3 at {option_3_coord}")
                pyautogui.click(option_3_coord[0], option_3_coord[1])
                time.sleep(0.2)
                logger.info(f"CLICKING: Clicking Submit at ({cx}, {cy})")
                pyautogui.click(cx, cy)
                return True
        else:
            logger.warning(f"Failed to identify Option 3 coord ({option_3_coord}) or Submit button ({submit_button}) within valid command dialog bounds.")
            return False

    # Check B: Agent error card (Agent terminated due to error)
    error_keywords = [
        "agent terminated due to error", 
        "terminated due to error", 
        "troubleshooting", 
        "copy debug info", 
        "dismiss"
    ]
    error_bounds = get_dialog_bounds(lines, error_keywords)
            
    if error_bounds:
        logger.info("Error state confirmed on screen!")
        # Find the blue "Retry" button
        blue_buttons = find_blue_buttons(image_path)
        logger.info(f"Found {len(blue_buttons)} blue button candidate(s) on screen.")
        
        if not blue_buttons:
            logger.warning("Error card detected, but no blue buttons found.")
            return False

        retry_word_coord = None
        for line in lines:
            for word in line.get("words", []):
                word_text = word.get("text", "")
                if "retry" in word_text.lower() or "retr" in word_text.lower():
                    retry_word_coord = (word["x"] + word["w"]//2, word["y"] + word["h"]//2)
                    logger.info(f"Found 'Retry' text at coordinates {retry_word_coord}")
                    break
            if retry_word_coord:
                break

        target_button = None
        
        # Enforce spatial constraint: button center must be inside the error dialog bounds
        valid_buttons = []
        for btn in blue_buttons:
            bx, by = btn['center']
            if (error_bounds["min_x"] <= bx <= error_bounds["max_x"]) and (error_bounds["min_y"] <= by <= error_bounds["max_y"]):
                valid_buttons.append(btn)
                
        if retry_word_coord:
            # If "Retry" text is found, find the closest valid button within 60px
            min_dist = float('inf')
            for btn in valid_buttons:
                bx, by = btn['center']
                dist = math.hypot(bx - retry_word_coord[0], by - retry_word_coord[1])
                if dist < min_dist and dist <= 60:
                    min_dist = dist
                    target_button = btn
        
        if not target_button and valid_buttons:
            # Fallback: Pick the valid button closest to "dismiss" or "copy debug info" if present,
            # or just pick the best valid button in the bounds
            target_button = valid_buttons[0]

        if target_button:
            cx, cy = target_button['center']
            logger.info(f"SUCCESS: Target blue 'Retry' button identified at coordinate ({cx}, {cy})")
            
            if dry_run:
                logger.info(f"[DRY RUN] Would click at ({cx}, {cy})")
                try:
                    if image_path:
                        img = Image.open(image_path)
                    else:
                        img = pyautogui.screenshot()
                    
                    img_np = np.array(img)
                    x, y, w, h = target_button['box']
                    cv2.rectangle(img_np, (x, y), (x + w, y + h), (0, 0, 255), 2)
                    cv2.circle(img_np, (cx, cy), 5, (0, 0, 255), -1)
                    
                    if img_np.shape[2] == 4:
                        img_out = Image.fromarray(img_np, 'RGBA')
                    else:
                        img_out = Image.fromarray(img_np, 'RGB')
                    img_out.save("debug_click.png")
                    logger.info("Saved debug detection visualization to debug_click.png")
                except Exception as draw_err:
                    logger.error(f"Could not draw debug image: {draw_err}")
                return True
            else:
                logger.info(f"CLICKING: Performing click at ({cx}, {cy})")
                pyautogui.click(cx, cy)
                return True
                
    return False

def main():
    parser = argparse.ArgumentParser(
        description="Auto-Retry & Command Approval Clicker for Antigravity"
    )
    parser.add_argument(
        "--interval", type=float, default=2.0,
        help="Seconds between screen checks (default: 2.0)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Detect the button and save debug_click.png without performing the actual click"
    )
    parser.add_argument(
        "--test-image", type=str, default="",
        help="Test detection on a static image file instead of live screen"
    )
    
    args = parser.parse_args()
    
    # Resolve helper paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ocr_script = os.path.join(script_dir, "ocr_helper.ps1")
    
    if not os.path.exists(ocr_script):
        logger.critical(f"OCR Helper script not found at {ocr_script}")
        sys.exit(1)
        
    logger.info("==================================================")
    logger.info("🟢 Antigravity Auto-Retry & Approval Clicker Started")
    logger.info(f"   Interval: {args.interval}s | Dry Run: {args.dry_run}")
    logger.info("   Press Ctrl+C to stop.")
    logger.info("==================================================")
    
    if args.test_image:
        logger.info(f"Running in test mode on static image: {args.test_image}")
        if not os.path.exists(args.test_image):
            logger.error(f"Test image not found: {args.test_image}")
            sys.exit(1)
            
        ocr_data = run_ocr(ocr_script, args.test_image)
        clicked = process_detection(ocr_data, args.test_image, dry_run=args.dry_run)
        if clicked:
            logger.info("Test passed: Action identified successfully!")
        else:
            logger.warning("Test warning: No action identified in test image.")
        sys.exit(0)

    # Main infinite loop
    try:
        while True:
            ocr_data = run_ocr(ocr_script)
            clicked = process_detection(ocr_data, None, dry_run=args.dry_run)
            
            if clicked:
                time.sleep(5.0)
            else:
                time.sleep(args.interval)
                
    except KeyboardInterrupt:
        logger.info("🛑 Stopped by user.")
    except Exception as e:
        logger.fatal(f"Fatal error in main loop: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
