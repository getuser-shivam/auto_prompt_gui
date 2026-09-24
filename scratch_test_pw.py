import logging
import sys
import time

logger = logging.getLogger("PlaywrightBrowserManager")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [Playwright] %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

import playwright_browser_manager
pw = playwright_browser_manager.PlaywrightBrowserManager()
print(f"Playwright worker initialized: {pw._worker.is_alive()}")
print("Attempting to launch AI studio browser...")
res = pw.launch_ai_studio_browser()
print(f"Launch result: {res}")
if res:
    print(f"Connected: {pw.is_connected()}")
    print("Generating state:", pw.is_generating())
    print("Wait 5s for load...")
    time.sleep(5)
    print("Sending prompt...")
    try:
        p_res = pw.send_prompt("Hello, this is a test prompt from playwright.")
        print("Prompt result:", p_res)
    except Exception as e:
        print("Send prompt error:", e)
