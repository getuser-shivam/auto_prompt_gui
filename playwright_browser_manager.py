#!/usr/bin/env python3
"""
Playwright Browser Manager — High-precision, DOM-level browser automation engine
for Google AI Studio and web-based AI workspaces.

Connects directly via Chrome DevTools Protocol (CDP) or launches persistent browser contexts,
completely eliminating screen-scraping, OCR, and OS-level window focus dependency.
"""

import os
import sys
import time
import json
import logging
import threading
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger("PlaywrightBrowserManager")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [Playwright] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class PlaywrightWorker(threading.Thread):
    """
    Dedicated worker thread running the Playwright sync loop.
    Guarantees thread-safe access from Tkinter GUI or background workflow threads.
    """
    def __init__(self):
        super().__init__(name="PlaywrightWorkerThread", daemon=True)
        import queue
        self._q = queue.Queue()
        self._ready_event = threading.Event()
        self.playwright = None
        self.browser = None
        self.context = None
        self.active_page = None
        self._connected = False
        self._cdp_port = 9222
        self._browser_proc = None

    def run(self):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                self.playwright = p
                self._ready_event.set()
                logger.info("Playwright worker loop started.")

                while True:
                    task = self._q.get()
                    if task is None:
                        break
                    fn, fut = task
                    try:
                        res = fn(self)
                        fut["result"] = res
                    except Exception as e:
                        fut["error"] = e
                    finally:
                        fut["event"].set()
                        self._q.task_done()

                # Cleanup on exit
                if self.context:
                    try:
                        self.context.close()
                    except Exception:
                        pass
                if self.browser:
                    try:
                        self.browser.close()
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Fatal Playwright worker error: {e}")
            self._ready_event.set()

    def execute(self, fn: Callable[['PlaywrightWorker'], Any], timeout: float = 60.0) -> Any:
        """Execute a function inside the Playwright worker thread and return the result."""
        if not self._ready_event.is_set():
            self._ready_event.wait(timeout=10.0)

        fut = {"event": threading.Event(), "result": None, "error": None}
        self._q.put((fn, fut))
        if not fut["event"].wait(timeout=timeout):
            raise TimeoutError(f"Playwright worker task timed out after {timeout}s")
        if fut["error"] is not None:
            raise fut["error"]
        return fut["result"]


class PlaywrightBrowserManager:
    """
    Singleton manager providing high-level DOM automation for Google AI Studio.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, cdp_port: int = 9222):
        if self._initialized:
            return
        self._initialized = True
        self.cdp_port = cdp_port
        self._worker: Optional[PlaywrightWorker] = None
        self._browser_proc: Optional[subprocess.Popen] = None
        self._start_worker()

    def _start_worker(self):
        if self._worker is None or not self._worker.is_alive():
            self._worker = PlaywrightWorker()
            self._worker.start()
            self._worker._ready_event.wait(timeout=5.0)

    # ═══════════════════════════════════════════════════
    # CONNECTION & LAUNCH MANAGEMENT
    # ═══════════════════════════════════════════════════

    def is_connected(self) -> bool:
        """Check if currently connected to a browser page with active DOM."""
        if not self._worker or not self._worker.is_alive():
            return False
        try:
            def _check(w: PlaywrightWorker) -> bool:
                if not w._connected or not w.active_page:
                    return False
                try:
                    # Quick ping on the active page
                    _ = w.active_page.url
                    return True
                except Exception:
                    w._connected = False
                    w.active_page = None
                    return False
            return bool(self._worker.execute(_check, timeout=3.0))
        except Exception:
            return False

    def connect_cdp(self, port: Optional[int] = None) -> bool:
        """Connect to an existing browser instance running with --remote-debugging-port."""
        target_port = port or self.cdp_port

        def _connect(w: PlaywrightWorker) -> bool:
            try:
                endpoint = f"http://127.0.0.1:{target_port}"
                logger.info(f"Attempting CDP connection to {endpoint}...")
                browser = w.playwright.chromium.connect_over_cdp(endpoint)
                w.browser = browser

                # Find existing AI Studio tab or use first context page
                contexts = browser.contexts
                if not contexts:
                    logger.warning("CDP connected, but no browser contexts found.")
                    return False

                ctx = contexts[0]
                w.context = ctx

                # Search open pages for AI Studio
                ai_page = None
                for p in ctx.pages:
                    try:
                        u = (p.url or "").lower()
                        if "aistudio.google.com" in u:
                            ai_page = p
                            break
                    except Exception:
                        pass

                if not ai_page and ctx.pages:
                    ai_page = ctx.pages[0]

                if not ai_page:
                    ai_page = ctx.new_page()
                    ai_page.goto("https://aistudio.google.com/")

                w.active_page = ai_page
                w._connected = True
                logger.info(f"CDP Connected successfully to page: {ai_page.url}")
                return True
            except Exception as e:
                logger.debug(f"CDP connection attempt failed: {e}")
                w._connected = False
                return False

        try:
            return bool(self._worker.execute(_connect, timeout=6.0))
        except Exception as e:
            logger.debug(f"connect_cdp error: {e}")
            return False

    def launch_ai_studio_browser(self, url: str = "https://aistudio.google.com/") -> bool:
        """
        Launch Google Chrome with remote debugging enabled and the user's persistent profile.
        If Chrome is already open with CDP, attaches to it immediately.
        """
        # 1. Try connecting first if already running with CDP
        if self.connect_cdp():
            return True

        # 2. Locate Google Chrome executable
        chrome_paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ]
        exe = next((p for p in chrome_paths if os.path.exists(p)), None)
        if not exe:
            logger.error("Neither Google Chrome nor Microsoft Edge was found on this system.")
            return False

        # Persistent user data directory so Google account login persists
        profile_dir = os.path.expanduser(r"~\.google_ai_studio_playwright_profile")
        os.makedirs(profile_dir, exist_ok=True)

        cmd = [
            exe,
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            url
        ]

        logger.info(f"Launching automated browser with CDP enabled on port {self.cdp_port}...")
        try:
            proc = subprocess.Popen(cmd)
            self._browser_proc = proc
            # Poll for CDP availability
            for _ in range(15):
                time.sleep(1.0)
                if self.connect_cdp():
                    logger.info("Successfully connected to newly launched automated browser!")
                    return True
            logger.warning("Browser launched, but CDP connection timed out.")
            return False
        except Exception as e:
            logger.error(f"Failed to launch automated browser: {e}")
            return False

    def ensure_page(self) -> bool:
        """Ensure active_page is valid and on Google AI Studio."""
        if self.is_connected():
            return True
        # Try auto-connecting to existing CDP
        if self.connect_cdp():
            return True
        return False

    def get_url(self) -> str:
        """Get the current URL of the active page."""
        if not self.is_connected():
            return ""
        def _get(w: PlaywrightWorker) -> str:
            return w.active_page.url if w.active_page else ""
        return self._worker.execute(_get, timeout=3.0)

    # ═══════════════════════════════════════════════════
    # HIGH-LEVEL DOM AUTOMATION ACTIONS
    # ═══════════════════════════════════════════════════

    def send_prompt(self, prompt: str) -> str:
        """
        Directly fills the prompt into the chat textarea in the DOM and submits it.
        100% immune to clipboard corruption or focus issues.
        """
        def _send(w: PlaywrightWorker) -> str:
            page = w.active_page
            if not page:
                raise RuntimeError("No active Playwright page connected")

            # 1. Bring tab to front
            page.bring_to_front()

            # 2. Wait for login if needed
            while "welcome" in page.url or "accounts.google" in page.url or "sign-in" in page.url:
                logger.info(f"Waiting for user to log in... Current URL: {page.url}")
                time.sleep(2)
                page = w.active_page # Refresh page reference

            # 3. Locate chat prompt input textarea
            input_selectors = [
                'textarea[placeholder*="Make changes"]',
                'textarea[placeholder*="prompt"]',
                'textarea[placeholder*="ask for anything"]',
                'div[contenteditable="true"]',
                '.chat-input-textarea',
                'textarea',
            ]

            input_locator = None
            for sel in input_selectors:
                loc = page.locator(sel).first
                try:
                    if loc.is_visible(timeout=1000):
                        input_locator = loc
                        break
                except Exception:
                    pass

            if not input_locator:
                raise RuntimeError("Could not find chat input element in DOM")

            # Direct DOM fill
            input_locator.click()
            input_locator.fill(prompt)

            # 3. Locate and click Send button
            send_selectors = [
                'button[aria-label="Send"]',
                'button[aria-label*="Send prompt"]',
                'button:has-text("arrow_upward")',
                'button.send-button',
                'button[type="submit"]',
            ]

            submitted = False
            for sel in send_selectors:
                s_loc = page.locator(sel).first
                try:
                    if s_loc.is_visible(timeout=800):
                        s_loc.click()
                        submitted = True
                        break
                except Exception:
                    pass

            if not submitted:
                # Fallback: Press Enter inside the textarea
                input_locator.press("Enter")

            return f"✅ Prompt injected directly via Playwright DOM ({len(prompt)} chars)"

        return self._worker.execute(_send, timeout=15.0)

    def is_generating(self) -> Dict[str, Any]:
        """
        Inspects DOM elements directly to determine if Google AI Studio is generating.
        No screenshots, no OCR, 0ms latency.
        """
        def _check(w: PlaywrightWorker) -> Dict[str, Any]:
            page = w.active_page
            res = {
                "is_generating": False,
                "status_text": "",
                "has_stop_btn": False,
                "has_send_btn": False,
            }
            if not page:
                return res

            try:
                # 1. Stop button check
                stop_locators = [
                    'button[aria-label="Stop"]',
                    'button[aria-label*="Stop generating"]',
                    'button:has-text("Stop")',
                    '.stop-button',
                    'button:has(mat-icon:text-is("stop"))',
                    'button:has(mat-icon:text-is("crop_square"))',
                ]
                for sel in stop_locators:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=200):
                        res["has_stop_btn"] = True
                        res["is_generating"] = True
                        break

                # 2. Timer / status label check
                status_locators = [
                    'span:has-text("Running for")',
                    '[aria-label*="Running for"]',
                    '.model-status',
                    'span:has-text("Ran for")',
                ]
                for sel in status_locators:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=200):
                        t = loc.inner_text().strip()
                        res["status_text"] = t
                        if "running for" in t.lower() or "loading" in t.lower():
                            res["is_generating"] = True
                        break

                # 3. Send button check
                send_loc = page.locator('button[aria-label="Send"], button.send-button').first
                if send_loc.is_visible(timeout=200):
                    res["has_send_btn"] = True

            except Exception as e:
                logger.debug(f"is_generating DOM check error: {e}")

            return res

        if not self.is_connected():
            return {"is_generating": False, "status_text": "", "has_stop_btn": False, "has_send_btn": False}
        return self._worker.execute(_check, timeout=3.0)

    def wait_for_completion(
        self,
        timeout_s: float = 900.0,
        status_callback: Optional[Callable[[str, str], None]] = None,
        cancel_event: Optional[threading.Event] = None
    ) -> str:
        """
        Waits dynamically for the AI generation to finish using native DOM event/state tracking.
        Resolves instantly the exact millisecond the AI finishes or pre-ends.
        """
        start_time = time.time()
        was_generating = False

        if status_callback:
            status_callback("waiting", "🔵 AI processing: Monitoring generation status via DOM...")

        # Grace period for initial submission
        time.sleep(1.0)

        while True:
            if cancel_event and cancel_event.is_set():
                return "cancelled"

            elapsed = time.time() - start_time
            if elapsed >= timeout_s:
                logger.warning(f"Playwright DOM wait timed out after {timeout_s}s")
                return "timeout"

            # Check for errors in DOM
            errors = self.detect_errors()
            if errors:
                err_msg = " | ".join(errors)
                is_quota = any(k in err_msg.lower() for k in [
                    "quota", "exhausted", "rate limit", "overloaded", "resource has been exhausted", "try again later"
                ])
                if is_quota:
                    if status_callback:
                        status_callback("typing", "Quota exceeded. Auto-switching to next free model...")
                    rotated = self.rotate_model()
                    if rotated:
                        return "retry_with_new_model"
                if status_callback:
                    status_callback("error", f"❌ AI Studio Error: {err_msg}")
                return f"error: {err_msg}"

            # Check generation state
            gen_state = self.is_generating()
            is_gen = gen_state.get("is_generating", False)
            status_text = gen_state.get("status_text") or f"Running for {int(elapsed)}s"

            if is_gen:
                was_generating = True
                if status_callback:
                    status_callback("waiting", f"🔵 AI is generating ({status_text})")
            else:
                if was_generating:
                    # Generation completed or pre-ended!
                    if status_callback:
                        status_callback("waiting", "✅ Generation finished. Advancing immediately...")
                    time.sleep(0.5)  # Brief settling delay
                    return "done"
                else:
                    if elapsed > 2.5:
                        # Confirmed idle if we see the send button and not generating
                        if gen_state.get("has_send_btn", False):
                            return "done"

            time.sleep(1.0)

    def detect_errors(self) -> List[str]:
        """Detect any active error messages or quota exhaustion banners directly in DOM."""
        def _get_errors(w: PlaywrightWorker) -> List[str]:
            page = w.active_page
            if not page:
                return []
            error_selectors = [
                '.error-text',
                'mat-error',
                '.banner-error',
                '[role="alert"]',
                '.error-container',
                'snack-bar-container',
            ]
            found = []
            for sel in error_selectors:
                try:
                    locs = page.locator(sel).all()
                    for loc in locs:
                        if loc.is_visible(timeout=100):
                            t = loc.inner_text().strip()
                            if t and t not in found:
                                found.append(t)
                except Exception:
                    pass
            return found

        if not self.is_connected():
            return []
        try:
            return self._worker.execute(_get_errors, timeout=3.0)
        except Exception:
            return []

    def rotate_model(self) -> bool:
        """
        Deterministically switches the Google AI Studio model dropdown in the DOM to the next free tier.
        """
        def _rotate(w: PlaywrightWorker) -> bool:
            page = w.active_page
            if not page:
                return False

            try:
                # 1. Open Chat settings sidebar if not visible
                settings_btn = page.locator('button[aria-label*="Settings"], button[aria-label*="Chat settings"]').first
                if settings_btn.is_visible(timeout=500):
                    settings_btn.click()
                    time.sleep(0.3)

                # 2. Click model selector dropdown
                model_dropdown = page.locator('mat-select, [aria-label*="model"], .model-selector').first
                if model_dropdown.is_visible(timeout=1000):
                    model_dropdown.click()
                    time.sleep(0.4)

                    # 3. Select next free tier option
                    free_models = [
                        "Gemini 2.5 Flash",
                        "Gemini 2.0 Flash",
                        "Gemini Flash Lite",
                        "Gemini 1.5 Flash",
                        "Gemini 1.5 Pro",
                        "Gemini 2.5 Pro",
                    ]
                    for m_name in free_models:
                        opt = page.locator(f'mat-option:has-text("{m_name}")').first
                        if opt.is_visible(timeout=300):
                            opt.click()
                            time.sleep(0.3)
                            logger.info(f"Playwright DOM rotated model to: {m_name}")
                            return True

                return False
            except Exception as e:
                logger.error(f"Playwright model rotation error: {e}")
                return False

        if not self.is_connected():
            return False
        try:
            return bool(self._worker.execute(_rotate, timeout=10.0))
        except Exception:
            return False

    def refresh_page(self) -> bool:
        """Reloads the active Google AI Studio tab cleanly via DOM."""
        def _reload(w: PlaywrightWorker) -> bool:
            page = w.active_page
            if not page:
                return False
            page.reload(wait_until="domcontentloaded")
            return True

        if not self.is_connected():
            return False
        try:
            return bool(self._worker.execute(_reload, timeout=15.0))
        except Exception:
            return False


# Global singleton instance helper
_manager_instance: Optional[PlaywrightBrowserManager] = None

def get_playwright_manager() -> PlaywrightBrowserManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = PlaywrightBrowserManager()
    return _manager_instance
