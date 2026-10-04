#!/usr/bin/env python3
"""
Playwright Browser Manager — High-precision, DOM-level browser automation engine
for Google AI Studio and web-based AI workspaces.

Connects through Chrome DevTools Protocol (CDP) for direct DOM control when a debug endpoint is available.
EditorBridge can retain UI Automation as a compatibility fallback for ordinary browser windows.
"""

import os
import sys
import time
import json
import logging
import threading
import subprocess
import contextvars
import re
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
        self._fatal_error = None
        self.playwright = None
        self.browser = None
        self.context = None
        self.active_page = None
        self.pages = {}
        self.active_session_id = "default"
        self.submission_state = {}
        self.usage_state = {}
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
            self._fatal_error = e
            logger.error(f"Fatal Playwright worker error: {e}")
            self._ready_event.set()

    def execute(self, fn: Callable[['PlaywrightWorker'], Any], timeout: float = 60.0) -> Any:
        """Execute a function inside the Playwright worker thread and return the result."""
        if not self._ready_event.wait(timeout=10.0):
            raise RuntimeError("Playwright worker did not finish starting")
        if not self.is_alive():
            detail = f": {self._fatal_error}" if self._fatal_error else ""
            raise RuntimeError(f"Playwright worker is unavailable{detail}")

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
        self._session_context = contextvars.ContextVar("playwright_browser_session", default="default")
        self._start_worker()

    def _session_id(self) -> str:
        return self._session_context.get() or "default"

    def _execute(self, fn: Callable[[PlaywrightWorker], Any], timeout: float = 60.0) -> Any:
        """Run a browser operation against the page assigned to the calling workflow."""
        session_id = self._session_id()

        def _in_session(worker: PlaywrightWorker):
            previous_page = worker.active_page
            previous_session = worker.active_session_id
            worker.active_session_id = session_id
            worker.active_page = worker.pages.get(session_id)
            try:
                result = fn(worker)
                if worker.active_page is not None:
                    worker.pages[session_id] = worker.active_page
                return result
            finally:
                worker.active_page = previous_page
                worker.active_session_id = previous_session

        return self._worker.execute(_in_session, timeout=timeout)

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
                if not w.active_page:
                    return False
                try:
                    # Quick ping on the active page
                    _ = w.active_page.url
                    return True
                except Exception:
                    w.pages.pop(w.active_session_id, None)
                    w._connected = bool(w.pages)
                    return False
            return bool(self._execute(_check, timeout=3.0))
        except Exception:
            return False

    def connect_cdp(self, port: Optional[int] = None) -> bool:
        """Connect to an existing browser instance running with --remote-debugging-port."""
        target_port = port or self.cdp_port
        session_id = self._session_id()

        def _connect(w: PlaywrightWorker) -> bool:
            try:
                endpoint = f"http://127.0.0.1:{target_port}"
                browser = w.browser
                if browser is not None:
                    try:
                        _ = browser.contexts
                    except Exception:
                        browser = None
                        w.browser = None
                        w.context = None
                if browser is None:
                    logger.info(f"Attempting CDP connection to {endpoint}...")
                    browser = w.playwright.chromium.connect_over_cdp(endpoint)
                    w.browser = browser

                contexts = browser.contexts
                if not contexts:
                    logger.warning("CDP connected, but no browser contexts found.")
                    return False

                assigned_pages = list(w.pages.values())
                ctx = next((c for c in contexts if any("aistudio.google.com" in (p.url or "").lower() for p in c.pages)), contexts[0])
                w.context = ctx

                # Give every workflow its own tab. The first session adopts an existing
                # AI Studio tab; later sessions get new tabs in the same signed-in context.
                ai_page = w.pages.get(session_id)
                if ai_page is not None:
                    try:
                        _ = ai_page.url
                    except Exception:
                        ai_page = None
                if ai_page is None:
                    for candidate_context in contexts:
                        for candidate in candidate_context.pages:
                            try:
                                if "aistudio.google.com" in (candidate.url or "").lower() and candidate not in assigned_pages:
                                    ai_page = candidate
                                    ctx = candidate_context
                                    break
                            except Exception:
                                continue
                        if ai_page:
                            break
                if ai_page is None:
                    ai_page = ctx.new_page()
                    ai_page.goto("https://aistudio.google.com/", wait_until="domcontentloaded", timeout=30000)

                page_url = (ai_page.url or "").lower()
                login_redirect = any(token in page_url for token in ("accounts.google.com", "signin", "sign-in"))
                if "aistudio.google.com" not in page_url and not login_redirect:
                    return False

                w.pages[session_id] = ai_page
                w.active_page = ai_page
                w._connected = True
                logger.info(f"CDP Connected workflow session '{session_id}' to page: {ai_page.url}")
                return True
            except Exception as e:
                logger.debug(f"CDP connection attempt failed: {e}")
                w._connected = False
                return False

        try:
            return bool(self._execute(_connect, timeout=35.0))
        except Exception as e:
            logger.debug(f"connect_cdp error: {e}")
            return False

    @staticmethod
    def kill_chrome_processes(exe_name: str = "chrome.exe") -> int:
        """Kill all running Chrome (or msedge) processes. Returns the number of processes killed."""
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/IM", exe_name],
                capture_output=True, text=True, timeout=10
            )
            killed = result.stdout.count("SUCCESS")
            if killed:
                logger.info(f"Killed {killed} {exe_name} process(es) to free the user profile for CDP relaunch.")
                time.sleep(1.5)  # Wait for profile lock to be released
            return killed
        except Exception as e:
            logger.debug(f"kill_chrome_processes({exe_name}): {e}")
            return 0

    def launch_ai_studio_browser(self, url: str = "https://aistudio.google.com/") -> bool:
        """
        Launch Google Chrome with remote debugging enabled and the user's persistent profile.
        If Chrome is already open with CDP, attaches to it immediately.
        If Chrome is open WITHOUT CDP (user's regular session), kills it first then relaunches.
        """
        # 1. Try connecting first if already running with CDP
        if self.connect_cdp():
            try:
                def _navigate_existing(w: PlaywrightWorker) -> bool:
                    page = w.active_page
                    if not page:
                        return False
                    current_url = (page.url or "").lower()
                    target_url = (url or "").strip()
                    if target_url and "aistudio.google.com" in target_url.lower():
                        target_base = target_url.split("?")[0].rstrip("/")
                        current_base = current_url.split("?")[0].rstrip("/")
                        if target_base != current_base or ("apps/" in target_url and "apps/" not in current_url):
                            logger.info(f"Navigating connected AI Studio tab to project URL: {target_url}")
                            try:
                                page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                            except Exception as nav_e:
                                logger.warning(f"Navigation to {target_url} failed: {nav_e}")
                    return "aistudio.google.com" in (page.url or "").lower()
                return bool(self._execute(_navigate_existing, timeout=35.0))
            except Exception:
                return False

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

        # Use the user's REAL Chrome profile so they stay logged in to Google.
        # Chrome cannot share a profile between two running instances.
        # Since connect_cdp() above failed, Chrome must be running WITHOUT CDP.
        # We MUST kill it first so the profile lock is released, then relaunch with CDP.
        real_profile = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
        fallback_profile = os.path.expanduser(r"~\.ai_studio_chrome_profile")
        is_edge = "msedge.exe" in exe.lower()

        if os.path.isdir(real_profile) and not is_edge:
            profile_dir = real_profile
            # Kill Chrome so it releases its lock on the real profile
            killed = self.kill_chrome_processes("chrome.exe")
            if killed:
                logger.info(f"Killed {killed} Chrome instance(s) to allow CDP relaunch with real profile.")
            else:
                logger.info("No running Chrome detected — launching fresh with CDP.")
        else:
            # Edge or no Chrome installation — use persistent fallback (no need to kill)
            profile_dir = fallback_profile
            if is_edge:
                self.kill_chrome_processes("msedge.exe")
        os.makedirs(profile_dir, exist_ok=True)

        cmd = [
            exe,
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--profile-directory=Default",
            url
        ]

        logger.info(f"Launching automated browser with CDP enabled on port {self.cdp_port}...")
        try:
            proc = subprocess.Popen(cmd)
            self._browser_proc = proc
            # Poll for CDP availability (up to 20s)
            for attempt in range(20):
                time.sleep(1.0)
                if self.connect_cdp():
                    logger.info(f"Successfully connected to newly launched automated browser after {attempt+1}s!")
                    return True
            logger.warning("Browser launched, but CDP connection timed out after 20s.")
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
        return self._execute(_get, timeout=3.0)

    # ═══════════════════════════════════════════════════
    # HIGH-LEVEL DOM AUTOMATION ACTIONS
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _visible_chat_input(page):
        selectors = (
            # AI Studio app builder (project edit view)
            'div[contenteditable="true"][aria-label*="Make changes" i]',
            'div[contenteditable="true"][aria-label*="ask for anything" i]',
            'div[contenteditable="true"][placeholder*="Make changes" i]',
            'div[contenteditable="true"][placeholder*="ask for anything" i]',
            'ms-prompt-input div[contenteditable="true"]',
            'ms-autosize-textarea div[contenteditable="true"]',
            'ms-prompt-input textarea',
            # Standard textarea selectors
            'textarea[placeholder*="Make changes" i]',
            'textarea[placeholder*="prompt" i]',
            'textarea[placeholder*="ask for anything" i]',
            'textarea[placeholder*="chat" i]',
            'textarea[aria-label*="prompt" i]',
            # Generic contenteditable
            '[contenteditable="true"][role="textbox"]',
            'div[contenteditable="true"]',
            '.chat-input-textarea',
        )
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=250):
                    return locator
            except Exception:
                continue
        return None

    @staticmethod
    def _inspect_page(page, baseline_body="") -> Dict[str, Any]:
        """Read chat readiness, generation, model and visible usage hints from the DOM."""
        state = {
            "is_generating": False,
            "is_finished": False,
            "status_text": "",
            "has_stop_btn": False,
            "has_send_btn": False,
            "chat_ready": False,
            "chat_changed": False,
            "model": "",
            "usage_text": "",
            "usage_remaining": None,
            "url": page.url,
            "title": "",
            "is_ai_studio": "aistudio.google.com" in (page.url or "").lower(),
            "requires_login": any(token in (page.url or "").lower() for token in ("accounts.google.com", "signin", "sign-in")),
        }
        if state["requires_login"]:
            state["is_ai_studio"] = True
        try:
            state["title"] = page.title()
        except Exception:
            pass
        state["chat_ready"] = bool(PlaywrightBrowserManager._visible_chat_input(page))

        try:
            body_text = page.locator("body").inner_text(timeout=1000)
        except Exception:
            body_text = ""
        body_lines = [line.strip() for line in body_text.splitlines() if line.strip()]
        state["chat_changed"] = bool(baseline_body and body_text and body_text != baseline_body)

        # AI Studio often renders the selected model as a plain status line instead
        # of a button, e.g. "Gemini 3.8 Flash • Ran for 14s".
        for line in body_lines[:60]:
            if re.match(r"^Gemini\b", line, re.I) and re.search(r"\b(?:Flash|Pro|Lite|Thinking|Ultra|Nano)\b", line, re.I):
                state["model"] = re.split(r"\s*[•·|]\s*", line, maxsplit=1)[0][:100]
                break

        try:
            for selector in (
                'span:has-text("Running for")',
                '[aria-label*="Running for" i]',
                '.model-status',
                'span:has-text("Ran for")',
            ):
                locator = page.locator(selector).first
                if locator.is_visible(timeout=100):
                    text = (locator.inner_text(timeout=100) or "").strip()
                    if text:
                        state["status_text"] = text
                        break
        except Exception:
            pass

        try:
            controls = page.locator('button, [role="button"], [role="combobox"], mat-select').all()
            model_candidates = []
            for control in controls:
                try:
                    if not control.is_visible(timeout=50):
                        continue
                    label = " ".join(filter(None, [
                        control.get_attribute("aria-label"),
                        control.get_attribute("title"),
                        control.inner_text(timeout=50),
                    ])).strip()
                    icon_text = ""
                    icon = control.locator("mat-icon, [data-mat-icon-name]").first
                    try:
                        if icon.count():
                            icon_text = icon.inner_text(timeout=50).strip()
                    except Exception:
                        pass
                    combined = f"{label} {icon_text}".lower()
                    if any(token in combined for token in ("stop", "cancel", "stop_circle", "crop_square")):
                        state["has_stop_btn"] = True
                    if any(token in combined for token in ("send", "arrow_upward", "submit")):
                        state["has_send_btn"] = True
                    if "gemini" in combined or "flash" in combined or "pro" in combined:
                        model_candidates.append(label or icon_text)
                except Exception:
                    continue
            if model_candidates and not state["model"]:
                state["model"] = model_candidates[0][:100]
        except Exception:
            pass

        status_lower = state["status_text"].lower()
        if "running for" in status_lower or "loading" in status_lower or state["has_stop_btn"]:
            state["is_generating"] = True
        if "ran for" in status_lower:
            state["is_finished"] = True

        try:
            usage_lines = [
                line for line in body_lines
                if re.search(
                    r"\b(quota|rate limit|requests? (?:left|remaining)|tokens? (?:left|remaining|used|total)|"
                    r"(?:input|output|prompt|response) tokens?|remaining|resets? in|rpm|tpm|rpd)\b|"
                    r"\busage\s*(?:[:=]|of)\s*\d",
                    line, re.I,
                )
            ]
            if usage_lines:
                state["usage_text"] = " · ".join(dict.fromkeys(usage_lines[-3:]))[:240]
                remaining_match = re.search(
                    r"\b(\d+)\s+(?:requests?|prompts?|tokens?)\s+(?:left|remaining)\b|\b(?:remaining|left)\D{0,12}(\d+)\b",
                    state["usage_text"], re.I,
                )
                if remaining_match:
                    state["usage_remaining"] = int(next(group for group in remaining_match.groups() if group))
        except Exception:
            pass
        return state

    def send_prompt(self, prompt: str) -> str:
        """
        Directly fills the prompt into the chat textarea in the DOM and submits it.
        This path does not use clipboard paste or screen coordinates.
        """
        state = self.get_chat_status()
        if not state.get("connected"):
            raise RuntimeError("No Playwright browser page is connected for this workflow")
        if not state.get("is_ai_studio"):
            raise RuntimeError(f"Connected browser tab is not Google AI Studio: {state.get('url', '')}")

        deadline = time.time() + (120 if state.get("requires_login") else 25)
        while state.get("requires_login") or not state.get("chat_ready"):
            if not state.get("requires_login") and state.get("url") and "aistudio.google.com" not in state.get("url", "").lower():
                raise RuntimeError(f"Connected browser tab is not Google AI Studio: {state.get('url', '')}")
            if time.time() >= deadline:
                if state.get("requires_login"):
                    raise TimeoutError("Google AI Studio login was not completed within 120 seconds")
                raise RuntimeError("Google AI Studio is open, but its chat input was not found. Open a chat screen and try again.")
            time.sleep(1)
            state = self.get_chat_status()

        session_id = self._session_id()

        def _send(w: PlaywrightWorker) -> str:
            page = w.active_page
            if not page:
                raise RuntimeError("No active Playwright page connected")

            page_url = (page.url or "").lower()
            login_redirect = any(token in page_url for token in ("accounts.google.com", "signin", "sign-in"))
            if "aistudio.google.com" not in page_url and not login_redirect:
                raise RuntimeError(f"Connected browser tab is not Google AI Studio: {page.url}")

            # 1. Bring tab to front
            page.bring_to_front()

            if "aistudio.google.com" not in (page.url or "").lower():
                raise RuntimeError(f"The AI Studio chat session changed to another page: {page.url}")

            input_locator = self._visible_chat_input(page)
            if not input_locator:
                raise RuntimeError("Google AI Studio is open, but its chat input was not found. Open a chat screen and try again.")

            # ── DISABLE the file-upload + button so it can NEVER intercept clicks ──
            try:
                page.evaluate("""
                    // Hide all attachment / file-upload buttons in the chat toolbar
                    const selectors = [
                        'button[aria-label*="upload" i]',
                        'button[aria-label*="attach" i]',
                        'button[aria-label*="file" i]',
                        'button[aria-label*="image" i]',
                        'button.add-attachment-button',
                        'ms-prompt-actions button:first-child',
                        'mat-toolbar button:first-child',
                        'button.input-button:first-child',
                    ];
                    selectors.forEach(sel => {
                        document.querySelectorAll(sel).forEach(el => {
                            el.style.pointerEvents = 'none';
                            el.style.opacity = '0.3';
                            el.setAttribute('tabindex', '-1');
                            el.setAttribute('data-disabled-by-bot', '1');
                        });
                    });
                """)
            except Exception:
                pass

            baseline_body = ""
            # Click the chat box directly using Playwright's exact element reference — no coordinates
            input_locator.click()
            input_locator.fill(prompt)
            try:
                baseline_body = page.locator("body").inner_text(timeout=1000)
            except Exception:
                pass
            baseline_status = self._inspect_page(page).get("status_text", "")

            # Locate the enabled submit control (AI Studio renders this as an up arrow).
            send_selectors = [
                'button[aria-label="Send"]',
                'button[aria-label*="Send prompt"]',
                'button:has(mat-icon:text-is("arrow_upward"))',
                'button:has-text("arrow_upward")',
                'button.send-button',
            ]

            submitted = False
            for sel in send_selectors:
                s_loc = page.locator(sel).first
                try:
                    if s_loc.is_visible(timeout=800):
                        if not s_loc.is_enabled():
                            continue
                        s_loc.click()
                        submitted = True
                        break
                except Exception:
                    pass

            if not submitted:
                # Fallback for layouts that expose no accessible send control.
                input_locator.press("Control+Enter")

            w.submission_state[session_id] = {
                "started_at": time.time(),
                "baseline_body": baseline_body,
                "baseline_status": baseline_status,
                "prompt_length": len(prompt),
            }
            usage = w.usage_state.setdefault(session_id, {"submitted": 0, "quota_switches": 0, "last_model": ""})
            usage["submitted"] += 1

            return f"✅ Prompt injected directly via Playwright DOM ({len(prompt)} chars)"

        return self._execute(_send, timeout=30.0)

    def get_chat_status(self) -> Dict[str, Any]:
        """Return browser, chat, selected model and observed usage state for this workflow."""
        session_id = self._session_id()
        empty = {
            "connected": False, "is_ai_studio": False, "chat_ready": False,
            "url": "", "title": "", "model": "", "usage_text": "",
            "usage_remaining": None,
            "is_generating": False, "is_finished": False, "status_text": "",
            "submitted": 0, "quota_switches": 0,
        }
        if not self.is_connected():
            return empty

        def _read(w: PlaywrightWorker) -> Dict[str, Any]:
            page = w.active_page
            if not page:
                return dict(empty)
            baseline = (w.submission_state.get(session_id) or {}).get("baseline_body", "")
            state = self._inspect_page(page, baseline)
            state["connected"] = True
            telemetry = w.usage_state.get(session_id, {})
            state["submitted"] = telemetry.get("submitted", 0)
            state["quota_switches"] = telemetry.get("quota_switches", 0)
            state["last_model"] = telemetry.get("last_model", "")
            return state

        try:
            return self._execute(_read, timeout=4.0)
        except Exception:
            return empty

    def is_generating(self) -> Dict[str, Any]:
        """
        Inspects visible AI Studio DOM controls and status text for generation state.
        """
        session_id = self._session_id()

        def _check(w: PlaywrightWorker) -> Dict[str, Any]:
            page = w.active_page
            res = {
                "is_generating": False,
                "is_finished": False,
                "status_text": "",
                "has_stop_btn": False,
                "has_send_btn": False,
                "chat_ready": False,
                "chat_changed": False,
                "model": "",
                "usage_text": "",
            }
            if not page:
                return res
            try:
                baseline = (w.submission_state.get(session_id) or {}).get("baseline_body", "")
                res.update(self._inspect_page(page, baseline))
            except Exception as e:
                logger.debug(f"is_generating DOM check error: {e}")

            return res

        if not self.is_connected():
            return {"is_generating": False, "status_text": "", "has_stop_btn": False, "has_send_btn": False}
        return self._execute(_check, timeout=4.0)

    def wait_for_completion(
        self,
        timeout_s: float = 900.0,
        status_callback: Optional[Callable[[str, str], None]] = None,
        cancel_event: Optional[threading.Event] = None,
        auto_rotate: bool = True,
    ) -> str:
        """
        Waits dynamically for the AI generation to finish using native DOM event/state tracking.
        Resolves instantly the exact millisecond the AI finishes or pre-ends.
        """
        start_time = time.time()
        was_generating = False
        stable_idle_count = 0
        session_id = self._session_id()

        try:
            submission = self._execute(lambda w: dict(w.submission_state.get(session_id) or {}), timeout=3.0)
        except Exception:
            submission = {}

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
            errors = self.detect_errors(submission.get("baseline_body", ""))
            if errors:
                err_msg = " | ".join(errors)
                is_quota = any(k in err_msg.lower() for k in [
                    "quota", "exhausted", "rate limit", "overloaded", "resource has been exhausted", "try again later"
                ])
                if is_quota:
                    if auto_rotate and status_callback:
                        status_callback("typing", "Quota exceeded. Switching to another available Gemini model...")
                    if auto_rotate:
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
            submitted_at = submission.get("started_at")
            submission_elapsed = time.time() - submitted_at if submitted_at else elapsed
            new_finish_status = bool(
                gen_state.get("is_finished")
                and gen_state.get("status_text")
                and gen_state.get("status_text") != submission.get("baseline_status", "")
            )

            if is_gen:
                was_generating = True
                stable_idle_count = 0
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
                    if not submitted_at:
                        # This path waits for an already-running generation before a new send.
                        if elapsed > 2.5 and gen_state.get("has_send_btn", False):
                            return "done"
                    else:
                        # A response must be observed after the submit. Never report success
                        # merely because the chat was idle before it started generating.
                        observed = bool(gen_state.get("chat_changed") or new_finish_status)
                        if observed and gen_state.get("has_send_btn", False):
                            stable_idle_count += 1
                            if new_finish_status or (submission_elapsed >= 8.0 and stable_idle_count >= 3):
                                if "ran for 0s" in status_text.lower() or "ran for 0 s" in status_text.lower():
                                    errors = self.detect_errors(submission.get("baseline_body", ""))
                                    if errors:
                                        err_msg = " | ".join(errors)
                                        if status_callback:
                                            status_callback("error", f"❌ AI Studio Error: {err_msg}")
                                        return f"error: {err_msg}"
                                if status_callback:
                                    status_callback("waiting", "✅ Generation finished. Advancing to the next step...")
                                return "done"
                        else:
                            stable_idle_count = 0
                        if submission_elapsed >= 12.0 and not observed:
                            return "error: Prompt submission was not confirmed by the AI Studio chat. Check the chat screen and send control."

            time.sleep(1.0)

    def detect_errors(self, baseline_body: str = "") -> List[str]:
        """Detect new visible errors, including quota notices rendered inside the chat."""
        def _get_errors(w: PlaywrightWorker) -> List[str]:
            page = w.active_page
            if not page:
                return []
            try:
                body = page.locator("body").inner_text(timeout=750)
            except Exception:
                body = ""
            baseline_flat = " ".join((baseline_body or "").casefold().split())
            body_flat = " ".join((body or "").casefold().split())
            error_selectors = [
                '.error-text',
                'mat-error',
                '.banner-error',
                '[role="alert"]',
                '.error-container',
                'snack-bar-container',
            ]
            found = []

            def add_if_new(message):
                message = " ".join((message or "").split())
                if not message:
                    return
                normalized = message.casefold()
                current_count = body_flat.count(normalized) if body_flat else 0
                old_count = baseline_flat.count(normalized) if baseline_flat else 0
                if current_count > old_count and message not in found:
                    found.append(message)

            for sel in error_selectors:
                try:
                    locs = page.locator(sel).all()
                    for loc in locs:
                        if loc.is_visible(timeout=100):
                            add_if_new(loc.inner_text(timeout=100))
                except Exception:
                    pass

            quota_pattern = re.compile(
                r"(?:quota.{0,40}(?:exceed|limit|exhaust)|(?:rate|request) limit|"
                r"too many requests|resource[_\s-]*exhausted|try again later|429)",
                re.I,
            )
            for line in (line.strip() for line in body.splitlines()):
                if quota_pattern.search(line):
                    add_if_new(line)

            # Also detect general API/model errors (Invalid argument, unexpected error, etc.)
            general_error_pattern = re.compile(
                r"(?:invalid argument|invalid request|bad request|permission denied|"
                r"unexpected error|internal error|failed to generate|something went wrong)",
                re.I,
            )
            # Only match lines near error indicators (e.g. warning icon, "Ran for 0s")
            error_context_lines = [
                line.strip() for line in body.splitlines()
                if general_error_pattern.search(line.strip())
            ]
            for line in error_context_lines:
                add_if_new(line)

            return found

        if not self.is_connected():
            return []
        try:
            return self._execute(_get_errors, timeout=3.0)
        except Exception:
            return []

    def rotate_model(self) -> bool:
        """
        Switch to the next enabled Gemini model exposed by the signed-in AI Studio project.
        """
        session_id = self._session_id()

        def _rotate(w: PlaywrightWorker) -> bool:
            page = w.active_page
            if not page:
                return False

            try:
                before = self._inspect_page(page).get("model", "")
                model_dropdown = None
                selectors = (
                    'mat-select',
                    '[role="combobox"][aria-label*="model" i]',
                    'button[aria-label*="model" i]',
                    'button:has-text("Gemini")',
                    '.model-selector',
                )
                for selector in selectors:
                    candidate = page.locator(selector).first
                    try:
                        if candidate.is_visible(timeout=250):
                            model_dropdown = candidate
                            break
                    except Exception:
                        continue

                if model_dropdown is None:
                    settings_btn = page.locator('button[aria-label*="Settings" i], button[aria-label*="Chat settings" i]').first
                    try:
                        if settings_btn.is_visible(timeout=250):
                            settings_btn.click()
                            time.sleep(0.35)
                    except Exception:
                        pass
                    for selector in selectors:
                        candidate = page.locator(selector).first
                        try:
                            if candidate.is_visible(timeout=250):
                                model_dropdown = candidate
                                break
                        except Exception:
                            continue

                if model_dropdown is None:
                    return False
                model_dropdown.click()
                time.sleep(0.35)

                options = []
                for option in page.locator('mat-option, [role="option"], [role="menuitem"]').all():
                    try:
                        if option.is_visible(timeout=50):
                            name = " ".join(filter(None, [
                                option.get_attribute("aria-label"),
                                option.get_attribute("title"),
                                option.inner_text(timeout=100),
                            ])).strip()
                            lower_name = name.casefold()
                            if not name or "gemini" not in lower_name:
                                continue
                            if any(term in lower_name for term in ("unavailable", "not available", "upgrade to", "coming soon")):
                                continue
                            try:
                                if not option.is_enabled():
                                    continue
                            except Exception:
                                pass
                            selected = (option.get_attribute("aria-selected") or "").lower() == "true"
                            options.append((name, option, selected))
                    except Exception:
                        continue
                if len(options) < 2:
                    return False

                # Sort available model options according to user preference order:
                # Google Pro -> Gemini 3.8 -> Gemini 3.7 -> Gemini 3.1 -> 2.5 -> 2.0 -> etc.
                def _model_preference_rank(model_name: str) -> tuple:
                    n = model_name.casefold()
                    if "pro" in n:
                        if "3.1" in n or "3" in n:
                            tier = 1  # Gemini 3.1 Pro / 3 Pro
                        elif "2.5" in n:
                            tier = 2  # Gemini 2.5 Pro
                        elif "1.5" in n:
                            tier = 3  # Gemini 1.5 Pro
                        else:
                            tier = 4  # Generic Pro
                    elif "3.8" in n:
                        tier = 10     # Gemini 3.8
                    elif "3.7" in n:
                        tier = 20     # Gemini 3.7
                    elif "3.1" in n or "3" in n:
                        if "flash lite" in n or "lite" in n:
                            tier = 35 # Gemini 3.1 Flash Lite
                        else:
                            tier = 30 # Gemini 3.1 Flash
                    elif "2.5" in n:
                        tier = 40     # Gemini 2.5 Flash
                    elif "2.0" in n or "2" in n:
                        tier = 50     # Gemini 2.0 Flash
                    elif "1.5" in n:
                        tier = 60     # Gemini 1.5 Flash
                    elif "lite" in n:
                        tier = 70
                    else:
                        tier = 80
                    return (tier, n)

                options.sort(key=lambda item: _model_preference_rank(item[0]))

                current_index = next((i for i, (name, _, selected) in enumerate(options) if selected), -1)
                if current_index < 0 and before:
                    before_lower = before.casefold()
                    current_index = next((
                        i for i, (name, _, _) in enumerate(options)
                        if before_lower in name.casefold() or name.casefold() in before_lower
                    ), -1)
                next_option = None
                for offset in range(1, len(options)):
                    index = (current_index + offset) % len(options)
                    name, locator, _ = options[index]
                    if current_index < 0 and before and name.casefold() == before.casefold():
                        continue
                    if index != current_index:
                        next_option = (name, locator)
                        break
                if not next_option:
                    return False

                name, locator = next_option
                locator.click()
                time.sleep(0.4)
                after = self._inspect_page(page).get("model", "")
                if not after:
                    after = name
                telemetry = w.usage_state.setdefault(session_id, {"submitted": 0, "quota_switches": 0, "last_model": ""})
                telemetry["quota_switches"] += 1
                telemetry["last_model"] = after
                logger.info(f"Playwright DOM switched model from {before or 'unknown'} to {after}")
                return True
            except Exception as e:
                logger.error(f"Playwright model rotation error: {e}")
                return False

        if not self.is_connected():
            return False
        try:
            return bool(self._execute(_rotate, timeout=10.0))
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
            return bool(self._execute(_reload, timeout=15.0))
        except Exception:
            return False

    def republish_and_test(self) -> bool:
        """Publish or republish the app and leave the user on the AI Studio page."""
        republish_pattern = re.compile(r"\brepublish\b", re.I)
        publish_app_pattern = re.compile(r"\bpublish\s+(?:your\s+)?app\b", re.I)
        publish_pattern = re.compile(r"\bpublish\b", re.I)
        continue_pattern = re.compile(r"\bcontinue\b", re.I)
        visit_pattern = re.compile(r"\bvisit\b", re.I)

        def control_label(locator):
            values = []
            for getter in (
                lambda: locator.get_attribute("aria-label"),
                lambda: locator.get_attribute("title"),
                lambda: locator.inner_text(timeout=100),
            ):
                try:
                    value = getter()
                    if value:
                        values.append(value)
                except Exception:
                    continue
            return " ".join(" ".join(values).split())

        def matching_controls(page, pattern):
            found = []
            for locator in page.locator('button, a, [role="button"], [role="link"]').all():
                try:
                    if not locator.is_visible(timeout=50):
                        continue
                    try:
                        if not locator.is_enabled():
                            continue
                    except Exception:
                        pass
                    if pattern.search(control_label(locator)):
                        found.append(locator)
                except Exception:
                    continue
            return found

        def body_text(page):
            try:
                return page.locator("body").inner_text(timeout=750)
            except Exception:
                return ""

        def _start(w: PlaywrightWorker):
            page = w.active_page
            if not page or "aistudio.google.com" not in (page.url or "").lower():
                return "invalid_page"
            if not self._inspect_page(page).get("chat_ready"):
                return "not_chat"

            body = body_text(page)
            publish_app = matching_controls(page, publish_app_pattern)
            if publish_app:
                publish_app[-1].click()
                return "publish_submitted"

            if "control gemini api usage" in body.lower():
                continue_controls = matching_controls(page, continue_pattern)
                if continue_controls:
                    continue_controls[-1].click()
                    return "continued"

            republish_controls = matching_controls(page, republish_pattern)
            if republish_controls:
                republish_controls[-1].click()
                return "republish_clicked"

            publish_controls = matching_controls(page, publish_pattern)
            if not publish_controls:
                return "missing_publish"
            if len(publish_controls) > 1:
                publish_controls[-1].click()
                return "publish_submitted"
            # The single visible Publish control is the toolbar tab; open its panel.
            publish_controls[0].click()
            return "panel_opened"

        def _advance_publish_flow(w: PlaywrightWorker, allow_republish: bool):
            page = w.active_page
            if not page:
                return ""
            body = body_text(page)
            publish_app = matching_controls(page, publish_app_pattern)
            if publish_app:
                publish_app[-1].click()
                return "publish_submitted"

            if "control gemini api usage" in body.lower():
                continue_controls = matching_controls(page, continue_pattern)
                if continue_controls:
                    continue_controls[-1].click()
                    return "continued"

            if allow_republish:
                republish_controls = matching_controls(page, republish_pattern)
                if republish_controls:
                    republish_controls[-1].click()
                    return "republish_clicked"
            return ""

        def _deployment_state(w: PlaywrightWorker) -> Dict[str, Any]:
            page = w.active_page
            if not page:
                return {"visit": False, "republish": False, "in_progress": False, "wizard": False, "failed": True}
            body = body_text(page)
            lowered = body.lower()
            return {
                # Visit is only a readiness signal; it is deliberately never clicked.
                "visit": bool(matching_controls(page, visit_pattern)),
                "republish": bool(matching_controls(page, republish_pattern)),
                "in_progress": bool(re.search(r"\b(?:in progress|building|deploying|publishing)\b", lowered)),
                "wizard": any(text in lowered for text in ("control gemini api usage", "final touches", "publish your app")),
                "failed": any(text in lowered for text in ("deployment failed", "publish failed", "build failed")),
            }

        if not self.is_connected():
            return False
        try:
            action_state = self._execute(_start, timeout=12.0)
            if action_state in ("invalid_page", "not_chat", "missing_publish"):
                logger.warning(f"AI Studio publish action could not start: {action_state}")
                return False

            publish_started = action_state in ("republish_clicked", "publish_submitted")
            panel_open = action_state == "panel_opened"
            clicked_at = time.time()
            deadline = clicked_at + 180
            stable_ready = 0

            while time.time() < deadline:
                advance = self._execute(
                    lambda w, allow=not publish_started: _advance_publish_flow(w, allow),
                    timeout=4.0,
                )
                if advance in ("republish_clicked", "publish_submitted"):
                    publish_started = True
                elif advance == "continued":
                    panel_open = True

                state = self._execute(_deployment_state, timeout=4.0)
                if state.get("failed"):
                    logger.error("AI Studio reported a publish or deployment failure")
                    return False

                ready = bool(
                    publish_started
                    and state.get("visit")
                    and state.get("republish")
                    and not state.get("in_progress")
                    and not state.get("wizard")
                    and time.time() - clicked_at >= 4
                )
                if ready:
                    stable_ready += 1
                    if stable_ready >= 2:
                        logger.info("AI Studio publish/republish completed; left the page on the publish panel")
                        return True
                else:
                    stable_ready = 0

                # A panel can render asynchronously after the toolbar Publish click.
                if panel_open and advance == "":
                    time.sleep(0.4)
                else:
                    time.sleep(0.8)

            logger.warning("AI Studio did not confirm publish completion before the 180-second timeout")
            return False
        except Exception as e:
            logger.error(f"AI Studio publish/republish failed: {e}")
            return False


class PlaywrightBrowserSession:
    """Workflow-scoped view over the shared Playwright worker and browser context."""
    def __init__(self, manager: PlaywrightBrowserManager, session_id: str):
        self._manager = manager
        self._session_id = session_id or "default"

    def __getattr__(self, name):
        value = getattr(self._manager, name)
        if not callable(value):
            return value

        def _bound(*args, **kwargs):
            token = self._manager._session_context.set(self._session_id)
            try:
                return value(*args, **kwargs)
            finally:
                self._manager._session_context.reset(token)
        return _bound


# Global singleton instance helper
_manager_instance: Optional[PlaywrightBrowserManager] = None
_manager_instance_lock = threading.Lock()

def get_playwright_manager(session_id: Optional[str] = None):
    global _manager_instance
    with _manager_instance_lock:
        if _manager_instance is None:
            _manager_instance = PlaywrightBrowserManager()
        manager = _manager_instance
    if session_id:
        return PlaywrightBrowserSession(manager, str(session_id))
    return manager
