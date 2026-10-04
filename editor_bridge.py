#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Editor Bridge -- Sends prompts to AI coding editors.
Supports clipboard paste, task-file drop, auto-interact, and process launching.
"""

import os
import json
import subprocess
import time
import shutil
import threading
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Callable, Tuple, Any
from datetime import datetime
import logging

# OCR / Visual / Context modules — imported lazily or encapsulated to avoid hangs on Windows
_cv2 = None
_np = None
_AntigravityVisualDetector = None
_ContextAnalyzer = None

def get_cv2():
    global _cv2
    if _cv2 is None:
        try:
            import cv2
            _cv2 = cv2
        except ImportError:
            pass
    return _cv2

def get_np():
    global _np
    if _np is None:
        try:
            import numpy as np
            _np = np
        except ImportError:
            pass
    return _np

def get_visual_detector_class():
    global _AntigravityVisualDetector
    if _AntigravityVisualDetector is None:
        try:
            from visual_detector import AntigravityVisualDetector
            _AntigravityVisualDetector = AntigravityVisualDetector
        except ImportError:
            class StubDetector:
                _last_state = "unknown"
                def is_generating(self, hwnd=None): return False
            _AntigravityVisualDetector = StubDetector
    return _AntigravityVisualDetector

def get_context_analyzer_class():
    global _ContextAnalyzer
    if _ContextAnalyzer is None:
        try:
            from context_analyzer import ContextAnalyzer
            _ContextAnalyzer = ContextAnalyzer
        except ImportError:
            class StubAnalyzer:
                def __init__(self, path=None): self.project_path = path
                def enhance_prompt(self, prompt): return prompt
            _ContextAnalyzer = StubAnalyzer
    return _ContextAnalyzer

logger = logging.getLogger(__name__)

try:
    from playwright_browser_manager import get_playwright_manager
except ImportError:
    get_playwright_manager = None


class EditorBridge:
    """Bridge to interact with AI coding editors"""

    _window_assignment_lock = threading.RLock()
    _window_assignments: Dict[str, int] = {}
    _interaction_locks: Dict[Any, threading.RLock] = {}

    EDITORS = {
        "antigravity": {
            "display": "Antigravity",
            "process_names": ["antigravity", "antigravity.exe", "Antigravity.exe"],
            "task_dir": ".gemini",
            "task_file": "task.md",
            "icon": "⚡",
            "chat_hotkey": "ctrl+l",  # open main Gemini AI chat panel (Ctrl+I is inline chat)
            "thinking_keywords": ["thinking", "generating", "loading", "processing", "researching", "waiting", "input"],
        },
        "windsurf": {
            "display": "Windsurf",
            "process_names": ["windsurf", "Windsurf.exe", "Code.exe"],
            "task_dir": ".windsurf/tasks",
            "task_file": "auto_prompt_task.md",
            "icon": "🌊",
            "chat_hotkey": "ctrl+l",  # open Cascade chat
            "chat_command": "",
            "command_palette_hotkey": "",
            "thinking_keywords": ["thinking", "generating", "writing", "cascade"],
        },
        "windsurf_next": {
            "display": "Windsurf Next",
            "process_names": ["WindsurfNext.exe", "windsurf-next.exe", "Windsurf.exe", "Code.exe"],
            "task_dir": ".windsurf/tasks",
            "task_file": "auto_prompt_task.md",
            "icon": "🌊",
            "chat_hotkey": "ctrl+l",
            "thinking_keywords": ["thinking", "generating", "writing", "cascade"],
        },
        "cursor": {
            "display": "Cursor",
            "process_names": ["cursor", "Cursor.exe"],
            "task_dir": ".cursor",
            "task_file": "task.md",
            "icon": "🔮",
            "chat_hotkey": "ctrl+l",  # open chat
            "chat_command": "",
            "command_palette_hotkey": "",
            "thinking_keywords": ["thinking", "generating", "loading"],
        },
        "vscode": {
            "display": "VS Code",
            "process_names": ["Code.exe", "code.exe", "Visual Studio Code"],
            # VS Code doesn't watch a task folder by default; fall back to clipboard/file drop
            "task_dir": "",
            "task_file": "",
            "icon": "⌨️",
            # Chat shortcut on Windows (user can remap in VS Code)
            "chat_hotkey": "ctrl+alt+i",
            # Optional: use Command Palette to open the right panel
            "chat_command": "",
            "command_palette_hotkey": "ctrl+shift+p",
            "thinking_keywords": ["processing", "generating", "working"],
        },
        "codex": {
            "display": "Codex",
            "process_names": ["Codex.exe", "codex.exe", "codex", "OpenAI Codex.exe", "OpenAI.Codex.exe", "ChatGPT.exe"],
            "task_dir": "",
            "task_file": "",
            "icon": "C",
            "chat_hotkey": "ctrl+l",
            "chat_command": "",
            "command_palette_hotkey": "ctrl+shift+p",
            "thinking_keywords": ["processing", "generating", "working", "thinking", "busy"],
        },
        "clipboard": {
            "display": "Clipboard Only",
            "process_names": [],
            "task_dir": "",
            "task_file": "",
            "icon": "📋",
            "chat_hotkey": "",
            "thinking_keywords": [],
        },
        "groq": {
            "display": "Groq AI (API Only)",
            "process_names": [],
            "task_dir": "",
            "task_file": "",
            "icon": "⚡",
            "chat_hotkey": "",
            "thinking_keywords": ["thinking", "generating"],
        },
        "google_ai_studio": {
            "display": "Google AI Studio",
            "process_names": ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe"],
            "task_dir": "",
            "task_file": "",
            "icon": "G",
            "chat_hotkey": "", # Browser-based, usually just focus and type
            "thinking_keywords": ["thinking", "generating", "working"],
            "url": "https://aistudio.google.com/"
        },
    }

    def __init__(self, project_path: str = None, editor: str = "antigravity", browser_session_id: str = None):
        self._project_path = Path(project_path).resolve() if project_path else Path.cwd().resolve()
        self._editor = editor if editor in self.EDITORS else "antigravity"
        self.browser_session_id = browser_session_id or f"editor-{uuid.uuid4().hex}"
        self._mode = "clipboard"  # clipboard | file_drop | terminal | auto_interact
        self._auto_focus = True
        self.use_ocr_click = True
        self.refresh_before_step = False  # Keep the AI Studio chat session alive between workflow steps
        self.auto_rotate_model = True    # Auto-switch to another available model if quota is exceeded
        self.auto_republish_test = True  # Auto-publish or republish after workflow completion
        self.detected_browser_url = ""   # Stores last detected browser URL
        self.last_ai_studio_error = None # Stores last detected Google AI Studio error
        self._model_rotation_count = 0
        self._ai_studio_prompt_count = 0
        self._ai_studio_quota_switch_count = 0
        self._ai_studio_current_model = ""
        self._pre_prompt_errors = set()
        self._log_history: List[Dict] = []

        # Auto-interact settings
        self._completion_timeout = 300  # max seconds to wait per step
        self._poll_interval = 2.0  # seconds between completion checks
        self._post_completion_delay = 2.0  # cooldown after AI finishes
        self._cancel_wait = threading.Event()  # to cancel waiting early
        self._last_allow_time = 0.0  # limit frequency of check_and_allow

        # Status callback for GUI live updates
        self.on_status_change: Optional[Callable[[str, str], None]] = None  # (status, detail)

        # CodeX Smart Prompt Detection State
        self._codex_last_title = ""
        self._codex_stable_start = 0.0
        self._codex_last_pulse = 0.0

        # Autopilot Enhancements (lazy instantiated during send/wait)
        self._visual_detector = None
        self._context_analyzer = None
        self.use_autopilot_context = False

    @property
    def visual_detector(self):
        if self._visual_detector is None:
            v_class = get_visual_detector_class()
            self._visual_detector = v_class()
        return self._visual_detector

    @property
    def context_analyzer(self):
        if self._context_analyzer is None:
            c_class = get_context_analyzer_class()
            self._context_analyzer = c_class(self._project_path)
        return self._context_analyzer

    @property
    def project_path(self) -> Path:
        return self._project_path

    @project_path.setter
    def project_path(self, value):
        if value:
            try:
                self._project_path = Path(value).resolve()
            except Exception:
                self._project_path = Path.cwd().resolve()
        else:
            self._project_path = Path.cwd().resolve()
        # Update context analyzer path if it was already instantiated
        if self._context_analyzer is not None:
            self._context_analyzer.project_path = self._project_path

    @property
    def editor(self) -> str:
        return self._editor

    @editor.setter
    def editor(self, value: str):
        if value in self.EDITORS:
            self._editor = value

    @property
    def supported_editors(self) -> List[str]:
        return list(self.EDITORS.keys())

    @property
    def editor_display_name(self) -> str:
        return self.EDITORS[self._editor]["display"]

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_connected(self) -> bool:
        """Determines if the current editor window is visibly attached and running"""
        # If not a web browser or specialized target, fallback to generic running check
        if self._editor not in ["google_ai_studio"]:
            return self.is_editor_running()

        if get_playwright_manager:
            try:
                pw = get_playwright_manager(self.browser_session_id)
                state = pw.get_chat_status()
                if state.get("connected") and state.get("is_ai_studio"):
                    self.detected_browser_url = state.get("url", "")
                    return True
            except Exception:
                pass
        
        # For Google AI Studio, ensure a window matching the title is found
        hwnd = self._find_editor_window()
        if not hwnd:
            return False
        # Opportunistically detect and store current browser URL
        try:
            self.detect_browser_url(hwnd)
        except Exception:
            pass
        return True

    @mode.setter
    def mode(self, value: str):
        if value in ("clipboard", "file_drop", "terminal", "auto_interact"):
            self._mode = value

    def _log(self, message: str, status: str = "info"):
        """Internal logging with history and callback"""
        timestamp = datetime.now().isoformat()
        entry = {"timestamp": timestamp, "status": status, "message": message}
        self._log_history.append(entry)
        logger.info(f"[{status.upper()}] {message}")
        if self.on_status_change:
            self.on_status_change(status, message)

    def send_prompt(self, prompt: str) -> str:
        """Send a prompt to the selected editor using the configured mode"""
        timestamp = datetime.now().isoformat()

        try:
            # Codex — use CLI if mode is 'terminal', otherwise standard GUI paths
            if self._editor == "codex" and self._mode == "terminal":
                result = self._send_via_codex_cli(prompt)
            elif self._mode == "clipboard":
                result = self._send_via_clipboard(prompt)
            elif self._mode == "file_drop":
                result = self._send_via_file_drop(prompt)
            elif self._mode == "terminal":
                result = self._send_via_terminal(prompt)
            elif self._mode == "auto_interact":
                result = self._send_via_auto_interact(prompt)
            else:
                result = self._send_via_clipboard(prompt)

            self._log_history.append({
                "timestamp": timestamp,
                "editor": self._editor,
                "mode": self._mode,
                "prompt_preview": prompt[:100],
                "status": "sent",
                "result": result,
            })

            return result

        except Exception as e:
            error_msg = f"Failed to send prompt: {e}"
            self._log_history.append({
                "timestamp": timestamp,
                "editor": self._editor,
                "mode": self._mode,
                "prompt_preview": prompt[:100],
                "status": "error",
                "result": error_msg,
            })
            raise RuntimeError(error_msg)

    def send_and_wait(self, prompt: str) -> str:
        """Run one complete interaction without interleaving prompts in a shared editor window."""
        if self._editor == "google_ai_studio" and get_playwright_manager:
            try:
                if get_playwright_manager(self.browser_session_id).is_connected():
                    return self._send_and_wait_locked(prompt)
            except Exception:
                pass
        hwnd = self._find_editor_window()
        with self._interaction_lock(hwnd):
            return self._send_and_wait_locked(prompt)

    def _send_and_wait_locked(self, prompt: str) -> str:
        """
        Convenience method for auto_interact: send and block until done.
        Returns only after the conversation is confirmed done.
        """
        # Inject context only if autopilot is enabled, editor is antigravity, AND path exists
        if self.use_autopilot_context and self._editor == "antigravity":
            try:
                if self._project_path and self._project_path.exists():
                    prompt = self.context_analyzer.enhance_prompt(prompt)
            except Exception:
                pass
            
        old_mode = self.mode
        self.mode = "auto_interact"
        self._cancel_wait.clear()

        # Codex — use CLI if mode is 'terminal', otherwise standard GUI paths
        if self._editor == "codex" and self._mode == "terminal":
            self._emit_status("typing", "Running Codex CLI with prompt...")
            result = self._send_via_codex_cli(prompt)
            self._emit_status("done", "Codex CLI finished")
            return result

        # Guard: Ensure any ongoing Google AI Studio conversation is finished before refreshing or sending
        if self._editor == "google_ai_studio":
            hwnd = self._find_editor_window()
            gen_check = self._check_google_ai_studio_generation(hwnd)
            if gen_check.get("is_generating"):
                r_text = gen_check.get("running_text") or "ongoing generation"
                self._log(f"Previous conversation is still generating ({r_text}). Waiting for it to finish before proceeding...", "info")
                self._emit_status("waiting", f"🔵 Previous generation still running ({r_text}). Waiting before next send...")
                wait_res = self._wait_for_google_ai_studio_completion(hwnd)
                if wait_res == "cancelled":
                    return "⏹ Wait cancelled"
                elif wait_res and wait_res.startswith("error:"):
                    return f"❌ {wait_res}"

        # Refresh page before each step for Google AI Studio only
        if self._editor == "google_ai_studio" and getattr(self, "refresh_before_step", False):
            self.refresh_google_ai_studio()

        self._emit_status("typing", "Typing prompt into editor...")

        # Send the prompt into editor chat (with automated model rotation retry support)
        max_model_retries = 4
        retry_count = 0
        send_result = ""
        done = ""

        while retry_count <= max_model_retries:
            if self._cancel_wait.is_set():
                return "⏹ Wait cancelled"

            send_result = self._send_via_auto_interact(prompt)
            if self._editor == "google_ai_studio":
                self._ai_studio_prompt_count += 1

            self._emit_status("waiting", "Waiting for AI to finish...")
            done = self._wait_for_completion()

            if done == "retry_with_new_model":
                retry_count += 1
                self._emit_status("typing", f"🔄 Model rotated. Retrying prompt (attempt {retry_count}/{max_model_retries})...")
                self._log(f"Quota exceeded: Auto-rotated model, retrying prompt ({retry_count}/{max_model_retries})...", "warning")
                time.sleep(1.5)
                continue

            break

        if done == "cancelled":
            return f"{send_result} → ⏹ Wait cancelled"
        elif done == "timeout":
            return f"{send_result} → ⚠️ Timed out after {self._completion_timeout}s"
        elif done == "retry_with_new_model":
            return f"{send_result} → ❌ Quota exceeded on all available models"
        elif done and done.startswith("error:"):
            return f"{send_result} → ❌ {done}"

        # Step 3: Post-completion cooldown
        self._emit_status("cooldown", f"AI done. Cooling down {self._post_completion_delay}s...")
        time.sleep(self._post_completion_delay)

        self._emit_status("done", "Step complete")
        return f"{send_result} → ✅ AI conversation completed"

    def cancel_wait(self):
        """Cancel the current wait-for-completion"""
        self._cancel_wait.set()

    def _emit_status(self, status: str, detail: str):
        """Notify the GUI of status changes"""
        if self.on_status_change:
            try:
                self.on_status_change(status, detail)
            except Exception:
                pass

    @staticmethod
    def _format_ai_studio_usage(state: Dict[str, Any]) -> str:
        parts = [f"AI Studio · {state.get('model') or 'model unknown'}"]
        parts.append(f"steps sent: {state.get('submitted', 0)}")
        parts.append(f"quota switches: {state.get('quota_switches', 0)}")
        if state.get("usage_text"):
            parts.append(state["usage_text"])
        return " | ".join(parts)

    def _send_with_playwright(self, pw, prompt: str, state=None) -> str:
        state = state or pw.get_chat_status()
        remaining = state.get("usage_remaining")
        if self.auto_rotate_model and remaining is not None and remaining <= 1:
            self._emit_status("typing", f"Only {remaining} AI Studio request(s) remain on this model. Switching before send...")
            if pw.rotate_model():
                self._ai_studio_quota_switch_count += 1
                try:
                    state = pw.get_chat_status()
                    self._ai_studio_current_model = state.get("model", "")
                except Exception:
                    pass
                self._emit_status("waiting", self._format_ai_studio_usage(state))
        return pw.send_prompt(prompt)

    def _send_via_clipboard(self, prompt: str) -> str:
        """Copy prompt to clipboard and optionally focus editor"""
        try:
            # Use a cross-platform clipboard approach
            # On Windows, use subprocess with clip
            process = subprocess.Popen(
                ["clip"],
                stdin=subprocess.PIPE,
                shell=True,
            )
            process.communicate(input=prompt.encode("utf-16le"))

            result = f"✅ Prompt copied to clipboard ({len(prompt)} chars)"

            # Try to focus the editor window
            if self._auto_focus:
                self._try_focus_editor()

            return result

        except Exception as e:
            # Fallback: try tkinter clipboard
            try:
                import tkinter as tk
                temp_root = tk.Tk()
                temp_root.withdraw()
                temp_root.clipboard_clear()
                temp_root.clipboard_append(prompt)
                temp_root.update()
                temp_root.destroy()
                return f"✅ Prompt copied to clipboard ({len(prompt)} chars)"
            except Exception:
                return f"⚠️ Clipboard copy failed: {e}. Prompt saved to file instead."

    def _send_via_file_drop(self, prompt: str) -> str:
        """Write prompt to a task file that the editor can pick up"""
        editor_config = self.EDITORS[self._editor]
        task_dir = editor_config.get("task_dir", "")

        if not task_dir:
            return self._send_via_clipboard(prompt)

        full_task_dir = self.project_path / task_dir
        full_task_dir.mkdir(parents=True, exist_ok=True)

        task_file = full_task_dir / editor_config["task_file"]
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        content = f"""# Auto-Prompt Task
> Generated: {timestamp}
> Editor: {editor_config['display']}

## Task

{prompt}

---
*Auto-generated by MyCircle Auto-Prompt Workflow Engine*
"""

        task_file.write_text(content, encoding="utf-8")

        # Also create a trigger file that some editors watch
        trigger_file = full_task_dir / ".auto_prompt_trigger"
        trigger_file.write_text(timestamp, encoding="utf-8")

        return f"✅ Task written to {task_file.relative_to(self.project_path)}"

    def _send_via_terminal(self, prompt: str) -> str:
        """Send prompt via terminal / stdin pipe (for CLI-based editors)"""
        # Write to a temp prompt file
        prompt_file = self._project_path / ".auto_prompt_current.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        return f"✅ Prompt saved to {prompt_file.name} for terminal ingestion"

    def _try_focus_editor(self):
        """Try to focus the editor window using Windows APIs"""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            editor_config = self.EDITORS[self._editor]
            process_names = editor_config.get("process_names", [])

            found_hwnd = self._find_editor_window()

            if found_hwnd:
                user32.SetForegroundWindow(found_hwnd)
                logger.info(f"Focused editor window: {self._editor}")

        except Exception as e:
            logger.debug(f"Could not auto-focus editor: {e}")

    def is_editor_running(self) -> bool:
        """Check if the selected editor process is running"""
        process_names = self._get_process_names()

        if not process_names:
            return True  # clipboard mode always available

        try:
            output = subprocess.check_output(
                ["tasklist", "/FI", "STATUS eq RUNNING"],
                shell=True, text=True, stderr=subprocess.DEVNULL
            )
            for pname in process_names:
                if pname.lower() in output.lower():
                    return True
        except Exception:
            pass

        return False

    def launch_editor(self, workspace_path: str = None) -> bool:
        """Attempt to launch the selected editor"""
        target = workspace_path or str(self._project_path)

        accessibility_flag = "--force-renderer-accessibility"
        launch_commands = {
            "antigravity": ["antigravity", accessibility_flag, target],
            "windsurf": ["windsurf", accessibility_flag, target],
            "windsurf_next": ["windsurf-next", accessibility_flag, target],
            "cursor": ["cursor", accessibility_flag, target],
            "vscode": ["code", accessibility_flag, target],
            "codex": ["codex", "--cd", target],
            "google_ai_studio": ["explorer", "https://aistudio.google.com/"],
        }

        cmd = launch_commands.get(self._editor)
        if not cmd:
            return False

        try:
            # Handle Web/URL based editors
            if self._editor == "google_ai_studio":
                url = target if (target.startswith("http://") or target.startswith("https://")) else "https://aistudio.google.com/"
                if get_playwright_manager:
                    try:
                        pw = get_playwright_manager(self.browser_session_id)
                        if pw.launch_ai_studio_browser(url):
                            self._log(f"Launched Google AI Studio automated browser via Playwright DOM: {url}", "success")
                            return True
                    except Exception as e:
                        logger.warning(f"Playwright browser launch failed: {e}")
                self._log(f"Opening Google AI Studio project URL: {url}", "info")
                subprocess.Popen(["explorer", url], shell=False)
                return True

            if self._editor == "codex":
                existing_hwnd = self._find_editor_window()
                if existing_hwnd:
                    self._try_focus_editor()
                    return True
                
                # Try to launch the GUI app via AppID (UWP)
                try:
                    # Try to launch OpenAI Codex UWP app
                    appid = "OpenAI.Codex_2p2nqsd0c76g0!App"
                    self._log(f"Attempting to launch CodeX via AppID: {appid}", "info")
                    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appid}"], shell=False)
                    return True
                except Exception:
                    pass

                codex_env_path = os.getenv("CODEX_APP_PATH") or os.getenv("CODEX_PATH")
                if codex_env_path and os.path.isfile(codex_env_path):
                    subprocess.Popen(
                        [codex_env_path, "--cd", target],
                        shell=False,
                        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                    )
                    return True

            # Try to find the editor executable
            exe_path = shutil.which(cmd[0])
            if exe_path:
                if self._editor == "codex":
                    subprocess.Popen(
                        [exe_path, "--cd", target],
                        shell=False,
                        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                    )
                    return True
                else:
                    subprocess.Popen([exe_path, accessibility_flag, target], shell=False)
                    return True

            # Fallback: try common install paths on Windows
            common_paths = {
                "antigravity": [
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\antigravity\antigravity.exe"),
                ],
                "windsurf": [
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Windsurf\Windsurf.exe"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\windsurf\windsurf.exe"),
                ],
                "windsurf_next": [
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Windsurf Next\Windsurf Next.exe"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\windsurf-next\windsurf-next.exe"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Windsurf\Windsurf.exe"),
                ],
                "cursor": [
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\cursor\Cursor.exe"),
                ],
                "vscode": [
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
                ],
                "codex": [
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Codex\Codex.exe"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\OpenAI\Codex.exe"),
                    os.path.expandvars(r"%ProgramFiles%\Codex\Codex.exe"),
                    os.path.expandvars(r"%ProgramFiles%\OpenAI\Codex.exe"),
                    os.path.expandvars(r"%ProgramFiles(x86)%\Codex\Codex.exe"),
                    os.path.expandvars(r"%ProgramFiles(x86)%\OpenAI\Codex.exe"),
                ],
            }

            for path in common_paths.get(self._editor, []):
                if os.path.isfile(path):
                    if self._editor == "codex":
                        subprocess.Popen(
                            [path, "--cd", target],
                            shell=False,
                            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                        )
                    else:
                        subprocess.Popen([path, accessibility_flag, target], shell=False)
                    return True

            logger.warning(f"Could not find {self._editor} executable")
            return False

        except Exception as e:
            logger.error(f"Failed to launch editor: {e}")
            return False

    def _send_via_codex_cli(self, prompt: str) -> str:
        """Send prompt to the OpenAI Codex CLI (@openai/codex npm package).
        The CLI runs in the current project directory and streams output to stdout.
        """
        import shutil

        codex_exe = (
            os.getenv("CODEX_APP_PATH")
            or os.getenv("CODEX_PATH")
            or shutil.which("codex")
            or shutil.which("codex.cmd")
            # Force search in npm global bin for Windows
            or (r"C:\Users\xxixw\AppData\Roaming\npm\codex.cmd" if os.path.exists(r"C:\Users\xxixw\AppData\Roaming\npm\codex.cmd") else None)
        )

        if not codex_exe:
            logger.warning("Codex CLI not found on PATH. Falling back to clipboard.")
            return self._send_via_clipboard(prompt)

        self._emit_status("typing", "Sending prompt to Codex CLI…")

        try:
            # Codex CLI 'exec' command runs non-interactively.
            # Use --skip-git-repo-check to avoid errors if the project isn't a git repo.
            # Use --dangerously-bypass-approvals-and-sandbox is the correct flag name.
            result = subprocess.run(
                [codex_exe, "exec", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", prompt],
                cwd=str(self._project_path),
                capture_output=True,
                text=True,
                timeout=120,
            )

            output = (result.stdout or "").strip()
            errors = (result.stderr or "").strip()

            if result.returncode != 0:
                logger.warning(f"Codex CLI exited with code {result.returncode}: {errors}")
                summary = errors[:300] if errors else f"Exit code {result.returncode}"
                return f"⚠️ Codex CLI error: {summary}"

            summary = output[:500] if output else "(no output)"
            logger.info(f"Codex CLI finished: {len(output)} chars")
            return f"✅ Codex CLI completed. Response: {summary}"

        except subprocess.TimeoutExpired:
            logger.warning("Codex CLI timed out after 120s")
            return "⚠️ Codex CLI timed out (120 s)"
        except Exception as e:
            logger.error(f"Codex CLI error: {e}")
            return self._send_via_clipboard(prompt)

    def get_history(self) -> List[Dict]:
        """Return the send history"""
        return self._log_history.copy()

    def clear_history(self):
        """Clear the send history"""
        self._log_history.clear()

    # ═══════════════════════════════════════════════════
    # AUTO-INTERACT MODE
    # ═══════════════════════════════════════════════════
    def _send_via_auto_interact(self, prompt: str) -> str:
        """Focus editor, open chat panel, paste prompt, press Enter"""
        import ctypes
        from ctypes import wintypes

        editor_config = self.EDITORS[self._editor]
        user32 = ctypes.windll.user32

        # Special case for Virtual / API Only editors
        if self._editor == "groq":
            return self._send_via_clipboard(prompt) + " (Groq Virtual Editor Mode)"

        # Prefer the workflow's own DOM-connected AI Studio tab. Launch the managed
        # browser only when no ordinary browser window is available to use as fallback.
        if self._editor == "google_ai_studio" and get_playwright_manager:
            try:
                pw = get_playwright_manager(self.browser_session_id)
                if not pw.ensure_page() and not self._find_editor_window():
                    self._emit_status("waiting", "Opening a managed AI Studio browser tab...")
                    pw.launch_ai_studio_browser("https://aistudio.google.com/")
                if pw.is_connected():
                    state = pw.get_chat_status()
                    if state.get("is_ai_studio") and state.get("chat_ready"):
                        self._emit_status("waiting", self._format_ai_studio_usage(state))
                        return self._send_with_playwright(pw, prompt, state)
                    if state.get("requires_login"):
                        self._emit_status("warning", "Log into Google AI Studio in the managed browser; the workflow will resume after login.")
                        return self._send_with_playwright(pw, prompt, state)
                    if state.get("is_ai_studio"):
                        detail = "Google AI Studio is open, but a chat screen is not ready. Open or start a chat before running this workflow."
                        self._emit_status("error", detail)
                        raise RuntimeError(detail)
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning(f"Playwright AI Studio connection failed: {e}")

        # 1. Find and focus the editor window
        hwnd = self._find_editor_window()
        if not hwnd:
            # Try to launch the editor
            launched = self.launch_editor()
            if launched:
                time.sleep(5)  # wait for editor to start
                hwnd = self._find_editor_window()
            if not hwnd:
                return self._send_via_clipboard(prompt)  # fallback

        # If it's a web-based DOM editor like Google AI Studio, use specific DOM logic instead
        if self._editor == "google_ai_studio":
            if get_playwright_manager:
                try:
                    pw = get_playwright_manager(self.browser_session_id)
                    if pw.ensure_page():
                        state = pw.get_chat_status()
                        if not state.get("is_ai_studio") or not state.get("chat_ready"):
                            detail = f"Google AI Studio is connected, but no chat screen was detected ({state.get('url', 'unknown URL')}). Open a chat and retry."
                            self._emit_status("error", detail)
                            raise RuntimeError(detail)
                        self._emit_status("waiting", self._format_ai_studio_usage(state))
                        logger.info("Injecting prompt directly into the detected AI Studio chat via Playwright DOM...")
                        return self._send_with_playwright(pw, prompt, state)
                    else:
                        msg = "⚠️ Playwright CDP is not connected. Falling back to browser UI Automation. Use Open AI Studio for DOM control."
                        logger.warning(msg)
                        self._log(msg, "warning")
                        self._emit_status("warning", "Playwright CDP not found. Using UIA fallback.")
                except Exception as e:
                    if isinstance(e, RuntimeError):
                        raise
                    logger.warning(f"Playwright DOM prompt injection error: {e}. Falling back to Web UIA.")
            return self._send_via_web_uia(prompt, hwnd)

        # Bring window to front
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        time.sleep(0.2)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)

        # Step A: Triple Esc reset (clear any open popups/menus/selections)
        for _ in range(3):
            self._press_key("escape")
            time.sleep(0.1)

        # Step B: Focus Editor Group 1 (ensure we aren't stuck in a sidebar/terminal/auxiliary view)
        self._press_hotkey("ctrl+1")
        time.sleep(0.4)

        # Step C: Open/Focus chat panel with editor-specific hotkey
        chat_command = editor_config.get("chat_command", "")
        chat_hotkey = editor_config.get("chat_hotkey", "")
        if chat_command:
            palette_hotkey = editor_config.get("command_palette_hotkey", "ctrl+shift+p")
            if palette_hotkey:
                self._press_hotkey(palette_hotkey)
                time.sleep(0.6)
            self._clipboard_set(chat_command)
            time.sleep(0.1)
            self._press_hotkey("ctrl+v")
            time.sleep(0.2)
            self._press_key("enter")
            time.sleep(1.0)
        elif chat_hotkey:
            self._press_hotkey(chat_hotkey)
            time.sleep(1.2)  # wait for panel to open and take focus

        # 3. Copy prompt to clipboard
        self._clipboard_set(prompt)
        time.sleep(0.2)

        # 4. Paste (Ctrl+V)
        self._press_hotkey("ctrl+v")
        time.sleep(0.5)

        # 4b. Force React/Electron state update by typing a space and deleting it
        self._press_key("space")
        time.sleep(0.1)
        self._press_key("backspace")
        time.sleep(0.5)

        # 5. Press Enter to submit
        self._press_key("enter")
        time.sleep(0.3)

        return f"✅ Prompt auto-typed into {editor_config['display']} ({len(prompt)} chars)"

    def detect_browser_url(self, hwnd=None) -> Optional[str]:
        """Detect the active URL from the browser window using UIA or window properties."""
        if not hwnd:
            hwnd = self._find_editor_window()
        if not hwnd:
            return None

        try:
            import uiautomation as auto
            auto.SetGlobalSearchTimeout(0.5)

            window = auto.ControlFromHandle(hwnd)
            if not window or not window.Exists(1, 0.2):
                window = auto.WindowControl(searchDepth=1, handle=hwnd)

            if not window.Exists(1, 0.2):
                return None

            addr_ctrl = None
            # 1. Search by AutomationId
            for auto_id in ["urlbar-input", "address-edit-box", "view_1020"]:
                c = window.EditControl(searchDepth=6, AutomationId=auto_id)
                if c.Exists(0.4, 0.1):
                    addr_ctrl = c
                    break

            # 2. Search by Name
            if not addr_ctrl:
                for name in ["Address and search bar", "Search with Google or enter address", "Search or enter web address", "Address"]:
                    c = window.EditControl(searchDepth=6, Name=name)
                    if c.Exists(0.4, 0.1):
                        addr_ctrl = c
                        break

            # 3. Search by ClassName
            if not addr_ctrl:
                c = window.EditControl(searchDepth=6, ClassName="OmniboxViewViews")
                if c.Exists(0.4, 0.1):
                    addr_ctrl = c

            if addr_ctrl:
                url_val = ""
                try:
                    vp = addr_ctrl.GetValuePattern()
                    if vp:
                        url_val = (vp.Value or "").strip()
                except Exception:
                    pass

                if not url_val:
                    try:
                        url_val = (addr_ctrl.Name or "").strip()
                    except Exception:
                        pass

                if url_val:
                    if not url_val.startswith("http://") and not url_val.startswith("https://") and "://" not in url_val:
                        if "." in url_val:
                            url_val = "https://" + url_val
                    self.detected_browser_url = url_val
                    return url_val

            # Fallback: DocumentControl Name or ValuePattern
            doc = window.DocumentControl(searchDepth=8)
            if doc.Exists(0.5, 0.1):
                try:
                    vp = doc.GetValuePattern()
                    if vp and vp.Value:
                        self.detected_browser_url = vp.Value.strip()
                        return self.detected_browser_url
                except Exception:
                    pass

            # Fallback: Window Title check
            title = self._get_window_title(hwnd)
            if any(k in title.lower() for k in ["google ai studio", "aistudio", "gemini"]):
                self.detected_browser_url = "https://aistudio.google.com/"
                return self.detected_browser_url

        except Exception as e:
            logger.debug(f"detect_browser_url error: {e}")

        return None

    def refresh_google_ai_studio(self, hwnd=None) -> bool:
        """
        Refreshes the Google AI Studio browser page before executing a step.
        Waits for the page reload to complete and the chat prompt area to become ready.
        Only runs for google_ai_studio.
        """
        if self._editor != "google_ai_studio":
            return False

        if get_playwright_manager:
            try:
                pw = get_playwright_manager(self.browser_session_id)
                if pw.is_connected():
                    self._emit_status("refresh", "🔄 Refreshing Google AI Studio page via Playwright DOM...")
                    return pw.refresh_page()
            except Exception as e:
                logger.debug(f"Playwright refresh error: {e}")

        import ctypes
        user32 = ctypes.windll.user32

        if not hwnd:
            hwnd = self._find_editor_window()
        if not hwnd:
            logger.warning("Cannot refresh Google AI Studio: browser window not found")
            return False

        logger.info(f"🔄 Refreshing Google AI Studio page (HWND: {hwnd}) before step...")
        self._emit_status("refresh", "🔄 Refreshing Google AI Studio page before step...")

        try:
            # 1. Bring window to front
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            time.sleep(0.2)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.3)

            # 2. Trigger browser refresh (Ctrl+R)
            self._press_hotkey("ctrl+r")
            time.sleep(1.5)

            # 3. Wait for page reload to complete and chat screen to stabilize
            import uiautomation as auto
            window = auto.ControlFromHandle(hwnd)
            if not window or not window.Exists(1, 0.2):
                window = auto.WindowControl(searchDepth=1, handle=hwnd)

            doc = None
            max_wait = 20  # seconds
            start_time = time.time()

            while time.time() - start_time < max_wait:
                if self._cancel_wait.is_set():
                    return False

                if window and window.Exists(0.5, 0.1):
                    doc = window.DocumentControl(searchDepth=8)
                    if doc.Exists(0.5, 0.1):
                        doc_rect = doc.BoundingRectangle
                        if doc_rect and doc_rect.width > 100:
                            break
                time.sleep(1.0)

            # Stabilization delay for dynamic components
            time.sleep(2.0)

            # Check if any errors are present immediately after refresh
            errors = self.detect_google_ai_studio_errors(hwnd, doc=doc)
            if errors:
                logger.warning(f"Error detected on Google AI Studio after refresh: {errors}")

            self._emit_status("ready", "✅ Google AI Studio refreshed & ready")
            logger.info("Google AI Studio refreshed successfully.")
            return True

        except Exception as e:
            logger.error(f"Failed to refresh Google AI Studio: {e}")
            return False

    def detect_google_ai_studio_errors(self, hwnd=None, doc=None, allow_ocr: bool = False) -> List[str]:
        """
        Scans Google AI Studio chat screen for active error banners / messages.
        Returns list of detected error strings. Fast by default; OCR is opt-in to prevent lag.
        """
        error_keywords = [
            "unexpected error",
            "quota exceeded",
            "please try again later",
            "finish what you were doing",
            "resource has been exhausted",
            "resourceexhausted",
            "rate limit exceeded",
            "model is overloaded",
            "failed to generate",
            "something went wrong",
            "internal error",
            "invalid argument",
            "invalid request",
            "bad request",
            "permission denied",
        ]
        detected = []

        if get_playwright_manager:
            try:
                pw = get_playwright_manager(self.browser_session_id)
                if pw.is_connected():
                    pw_errors = pw.detect_errors()
                    if pw_errors:
                        return pw_errors
            except Exception as e:
                logger.debug(f"Playwright detect_errors: {e}")

        try:
            import uiautomation as auto

            if not doc:
                if not hwnd:
                    hwnd = self._find_editor_window()
                if hwnd:
                    window = auto.ControlFromHandle(hwnd)
                    if window and window.Exists(0.5, 0.1):
                        doc = window.DocumentControl(searchDepth=6)

            if doc and doc.Exists(0.5, 0.1):
                doc_rect = doc.BoundingRectangle
                chat_right = doc_rect.left + int(doc_rect.width * 0.45) if doc_rect else 999999

                # Scan text elements in Document (focusing on left chat screen pane)
                def scan_errors(ctrl, depth=0):
                    if depth > 6:
                        return
                    try:
                        name = (ctrl.Name or "").strip()
                        if name:
                            rect = ctrl.BoundingRectangle
                            is_in_chat = (rect is None or rect.left <= chat_right + 30)
                            if is_in_chat:
                                name_lower = name.lower()
                                for kw in error_keywords:
                                    if kw in name_lower:
                                        if name not in detected:
                                            detected.append(name)
                                        break
                        for child in ctrl.GetChildren():
                            scan_errors(child, depth + 1)
                    except Exception:
                        pass

                scan_errors(doc)

        except Exception as e:
            logger.debug(f"UIA error scan error: {e}")

        # OCR fallback only if explicitly allowed (avoids continuous PowerShell spawns)
        if not detected and allow_ocr:
            try:
                ocr_errors = self._scan_errors_via_ocr(hwnd)
                if ocr_errors:
                    detected.extend(ocr_errors)
            except Exception as e:
                logger.debug(f"OCR error scan error: {e}")

        if detected:
            self.last_ai_studio_error = " | ".join(detected)
            logger.warning(f"⚠️ Google AI Studio error(s) detected: {self.last_ai_studio_error}")
        else:
            self.last_ai_studio_error = None

        return detected

    def _scan_errors_via_ocr(self, hwnd=None) -> List[str]:
        """OCR-based error detector for Google AI Studio chat screen."""
        error_keywords = [
            "unexpected error",
            "quota exceeded",
            "try again later",
            "finish what you were doing",
            "resource has been exhausted",
            "rate limit",
            "model is overloaded",
            "something went wrong",
            "failed to generate",
            "invalid argument",
            "invalid request",
            "bad request",
            "permission denied",
        ]
        script_dir = os.path.dirname(os.path.abspath(__file__))
        ocr_script = os.path.join(script_dir, "ocr_helper.ps1")
        if not os.path.exists(ocr_script):
            return []

        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", ocr_script
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=10)
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout, strict=False)
                found = []
                for line in data.get("lines", []):
                    text = line.get("text", "")
                    text_lower = text.lower()
                    for kw in error_keywords:
                        if kw in text_lower:
                            clean_text = text.strip()
                            if clean_text not in found:
                                found.append(clean_text)
                            break
                return found
        except Exception:
            pass
        return []

    def find_and_click_ocr_target(
        self,
        target_keywords: List[str],
        region_filter: Optional[Tuple[float, float, float, float]] = None,
        hwnd: Optional[int] = None,
        click: bool = True
    ) -> Optional[Tuple[int, int]]:
        """
        Locates a UI element via OCR using spatial suppression and optionally clicks it.
        
        target_keywords: words or phrases to search for (case-insensitive)
        region_filter: tuple of (min_x, max_x, min_y, max_y). If floats <= 1.0,
                       treated as percentage of window / image dimension.
                       If > 1.0, treated as absolute coordinates.
        hwnd: window handle to capture (or uses _find_editor_window)
        click: if True, clicks the center of the matching element
        
        Returns: (x, y) coordinates of the target center, or None if not found.
        """
        import tempfile
        import pyautogui

        if hwnd is None:
            hwnd = self._find_editor_window()

        temp_img = None
        try:
            import pygetwindow as gw
            win = None
            if hwnd:
                wins = [w for w in gw.getAllWindows() if getattr(w, '_hWnd', 0) == hwnd]
                if wins:
                    win = wins[0]

            if win and win.width > 100 and win.height > 100:
                bbox = (win.left, win.top, win.width, win.height)
                img = pyautogui.screenshot(region=bbox)
                offset_x, offset_y = win.left, win.top
            else:
                img = pyautogui.screenshot()
                offset_x, offset_y = 0, 0

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                temp_img = tf.name
            img.save(temp_img)
            img_w, img_h = img.size

            script_dir = os.path.dirname(os.path.abspath(__file__))
            ocr_script = os.path.join(script_dir, "ocr_helper.ps1")
            if not os.path.exists(ocr_script):
                return None

            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", ocr_script,
                temp_img
            ]
            res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=12)
            if res.returncode != 0 or not res.stdout:
                return None

            data = json.loads(res.stdout, strict=False)

            # Resolve region filter bounds
            min_x_abs = 0
            max_x_abs = img_w
            min_y_abs = 0
            max_y_abs = img_h
            if region_filter:
                f_min_x, f_max_x, f_min_y, f_max_y = region_filter
                min_x_abs = int(f_min_x * img_w) if f_min_x <= 1.0 else f_min_x
                max_x_abs = int(f_max_x * img_w) if f_max_x <= 1.0 else f_max_x
                min_y_abs = int(f_min_y * img_h) if f_min_y <= 1.0 else f_min_y
                max_y_abs = int(f_max_y * img_h) if f_max_y <= 1.0 else f_max_y

            for line in data.get("lines", []):
                text = line.get("text", "")
                text_lower = text.lower()
                if any(k.lower() in text_lower for k in target_keywords):
                    words = line.get("words", [])
                    if not words:
                        continue
                    lx = words[0]["x"]
                    ly = words[0]["y"]
                    lw = (words[-1]["x"] + words[-1]["w"]) - words[0]["x"]
                    lh = max(w["h"] for w in words)
                    cx = lx + lw // 2
                    cy = ly + lh // 2

                    # Apply spatial suppression
                    if not (min_x_abs <= cx <= max_x_abs and min_y_abs <= cy <= max_y_abs):
                        continue

                    # Absolute screen coordinate
                    target_x = int(offset_x + cx)
                    target_y = int(offset_y + cy)

                    if click:
                        logger.info(f"OCR Match: '{text}' at ({target_x}, {target_y}) — Clicking target.")
                        pyautogui.click(target_x, target_y)
                        time.sleep(0.3)

                    return (target_x, target_y)

            return None
        except Exception as e:
            logger.debug(f"find_and_click_ocr_target failed: {e}")
            return None
        finally:
            if temp_img and os.path.exists(temp_img):
                try:
                    os.remove(temp_img)
                except Exception:
                    pass

    def rotate_google_ai_studio_model(self, hwnd=None) -> bool:
        """
        Rotates the active Google AI Studio model to another available model when quota is exceeded.
        Opens Chat settings sidebar if closed, clicks Model selector dropdown,
        cycles to an enabled model, and auto-clicks [Retry] if present.
        """
        if get_playwright_manager:
            try:
                pw = get_playwright_manager(self.browser_session_id)
                if not pw.is_connected():
                    pw.ensure_page()
                if pw.is_connected():
                    self._log("Rotating Google AI Studio model via Playwright DOM...", "info")
                    if pw.rotate_model():
                        self._ai_studio_quota_switch_count += 1
                        try:
                            self._ai_studio_current_model = pw.get_chat_status().get("model", "")
                        except Exception:
                            pass
                        return True
            except Exception as e:
                logger.debug(f"Playwright rotate_model: {e}")

        import ctypes
        import time
        import pyautogui
        pyautogui.FAILSAFE = False
        user32 = ctypes.windll.user32

        if hwnd is None:
            hwnd = self._find_editor_window()
        if not hwnd:
            logger.warning("rotate_google_ai_studio_model: Window handle not found")
            return False

        # 1. Bring window to front
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        time.sleep(0.2)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.4)

        self._emit_status("typing", "Rotating model: Opening Chat settings...")
        logger.info("Attempting Google AI Studio model rotation...")

        win_rect = self._get_window_rect(hwnd)
        if win_rect:
            w_left, w_top, w_right, w_bottom = win_rect
            w_width = w_right - w_left
            w_height = w_bottom - w_top
        else:
            w_left, w_top, w_width, w_height = 0, 0, 1200, 800

        # 2. Check if Chat settings sidebar is open; if closed, open it
        settings_open = False
        try:
            import uiautomation as auto
            window = auto.ControlFromHandle(hwnd)
            if window and window.Exists(1, 0.2):
                doc = window.DocumentControl(searchDepth=8)
                if doc.Exists(0.5, 0.1):
                    # Check for "Select model to use in Chat" label
                    lbl = doc.TextControl(searchDepth=14, Name="Select model to use in Chat")
                    if not lbl.Exists(0.2, 0.05):
                        lbl = doc.Control(searchDepth=14, Name="Select model to use in Chat")
                    if lbl.Exists(0.2, 0.05):
                        settings_open = True
                        logger.info("Chat settings panel is already open.")
        except Exception as e:
            logger.debug(f"UIA Chat settings check: {e}")

        if not settings_open:
            # Need to open Chat settings panel
            opened = False
            try:
                import uiautomation as auto
                window = auto.ControlFromHandle(hwnd)
                if window and window.Exists(1, 0.2):
                    doc = window.DocumentControl(searchDepth=8)
                    if doc.Exists(0.5, 0.1):
                        # Try finding Chat tab or Settings button
                        for btn_name in ["Chat", "• Chat", "Chat settings", "Settings", "Tune", "Parameters"]:
                            btn = doc.ButtonControl(searchDepth=14, Name=btn_name)
                            if btn.Exists(0.2, 0.05):
                                btn.Click(waitTime=0.2)
                                opened = True
                                logger.info(f"UIA clicked {btn_name} to open Chat settings")
                                break
                        # If not, look for button next to Publish
                        if not opened:
                            pub_btn = doc.ButtonControl(searchDepth=14, Name="Publish")
                            if pub_btn.Exists(0.2, 0.05):
                                p_rect = pub_btn.BoundingRectangle
                                if p_rect:
                                    settings_btn_x = p_rect.right + 25
                                    settings_btn_y = p_rect.top + p_rect.height // 2
                                    pyautogui.click(settings_btn_x, settings_btn_y)
                                    opened = True
                                    logger.info(f"Clicked Settings button next to Publish at ({settings_btn_x}, {settings_btn_y})")
            except Exception as e:
                logger.debug(f"UIA open settings search: {e}")

            if not opened:
                # OCR fallback to open settings / chat tab
                opened = bool(self.find_and_click_ocr_target(["chat", "settings"], region_filter=(0.55, 0.98, 0.04, 0.20), hwnd=hwnd))

            if not opened and win_rect:
                # Geometry fallback for settings icon next to Publish
                pyautogui.click(w_left + int(w_width * 0.965), w_top + int(w_height * 0.105))
                opened = True

            time.sleep(0.7)

        # 3. Locate and click the Model dropdown selector
        model_dropdown_clicked = False
        try:
            import uiautomation as auto
            window = auto.ControlFromHandle(hwnd)
            if window and window.Exists(1, 0.2):
                doc = window.DocumentControl(searchDepth=8)
                if doc.Exists(0.5, 0.1):
                    # Method A: Directly click beneath "Select model to use in Chat" label
                    lbl = doc.TextControl(searchDepth=14, Name="Select model to use in Chat")
                    if not lbl.Exists(0.2, 0.05):
                        lbl = doc.Control(searchDepth=14, Name="Select model to use in Chat")
                    if lbl.Exists(0.2, 0.05):
                        l_rect = lbl.BoundingRectangle
                        if l_rect and l_rect.width > 0:
                            drop_x = l_rect.left + 60
                            drop_y = l_rect.bottom + 25
                            pyautogui.click(drop_x, drop_y)
                            model_dropdown_clicked = True
                            logger.info(f"Clicked Model dropdown below label at ({drop_x}, {drop_y})")
                    
                    # Method B: Search controls in right pane with model keywords
                    if not model_dropdown_clicked:
                        doc_rect = doc.BoundingRectangle
                        chat_right = doc_rect.left + int(doc_rect.width * 0.45) if doc_rect else 0
                        def find_model_btn(ctrl, depth=0):
                            nonlocal model_dropdown_clicked
                            if model_dropdown_clicked or depth > 12:
                                return
                            try:
                                name = ctrl.Name or ""
                                rect = ctrl.BoundingRectangle
                                if rect and rect.left > chat_right and rect.top < (doc_rect.top + int(doc_rect.height * 0.40) if doc_rect else 400):
                                    if any(k in name.lower() for k in ["gemini", "flash", "pro", "select model"]):
                                        ctrl.Click(waitTime=0.2)
                                        model_dropdown_clicked = True
                                        logger.info(f"UIA clicked Model dropdown control: '{name}'")
                                        return
                                for child in ctrl.GetChildren():
                                    find_model_btn(child, depth + 1)
                            except Exception:
                                pass
                        find_model_btn(doc)
        except Exception as e:
            logger.debug(f"UIA Model dropdown search: {e}")

        if not model_dropdown_clicked:
            # Method C: OCR fallback
            ocr_pos = self.find_and_click_ocr_target(
                ["select model", "model", "flash", "gemini"],
                region_filter=(0.60, 0.98, 0.12, 0.35),
                hwnd=hwnd,
                click=True
            )
            if ocr_pos:
                model_dropdown_clicked = True

        if not model_dropdown_clicked and win_rect:
            # Method D: Geometric position in the right sidebar (~75% X, ~25.5% Y)
            drop_x = w_left + int(w_width * 0.75)
            drop_y = w_top + int(w_height * 0.255)
            pyautogui.click(drop_x, drop_y)
            model_dropdown_clicked = True
            logger.info(f"Clicked geometric Model dropdown at ({drop_x}, {drop_y})")

        time.sleep(0.5)

        # 4. Cycle to another available model
        self._model_rotation_count = getattr(self, "_model_rotation_count", 0) + 1
        model_selected = False

        # Try selecting from UIA dropdown options if open (in ascending preference order)
        try:
            import uiautomation as auto
            root = auto.GetRootControl()
            # Order: Google Pro -> Gemini 3.8 -> Gemini 3.7 -> Gemini 3.1 -> 2.5 -> 2.0 -> etc.
            available_targets = [
                "Gemini 3.1 Pro", "Gemini 3 Pro", "Gemini 2.5 Pro", "Gemini 1.5 Pro", "Gemini Pro",
                "Gemini 3.8 Flash", "Gemini 3.8",
                "Gemini 3.7 Flash", "Gemini 3.7",
                "Gemini 3.1 Flash", "Gemini 3.1 Flash Lite", "Gemini 3 Flash",
                "Gemini 2.5 Flash", "Gemini 2.0 Flash", "Gemini Flash Lite", "Gemini 1.5 Flash",
            ]
            # Offset targets based on rotation count so we cycle through them in order
            rotation_offset = (self._model_rotation_count - 1) % len(available_targets)
            ordered_targets = available_targets[rotation_offset:] + available_targets[:rotation_offset]
            for target_name in ordered_targets:
                opt = root.Control(searchDepth=10, Name=target_name)
                if opt.Exists(0.2, 0.05):
                    opt.Click(waitTime=0.2)
                    model_selected = True
                    logger.info(f"UIA selected preferred model: {target_name}")
                    break
        except Exception:
            pass

        if not model_selected:
            # Deterministic keyboard cycling:
            # Press Home to jump to top of list
            self._press_key("home")
            time.sleep(0.15)
            # Move to another option in the visible model menu.
            steps = (self._model_rotation_count % 4) + 1
            for _ in range(steps):
                self._press_key("down")
                time.sleep(0.12)
            # Select model
            self._press_key("enter")
            time.sleep(0.3)

        # Dismiss any leftover menu popup
        self._press_key("escape")
        time.sleep(0.3)

        self._log(f"Switched Google AI Studio to another available model (rotation #{self._model_rotation_count})", "success")
        self._ai_studio_quota_switch_count += 1
        self._ai_studio_current_model = f"rotation #{self._model_rotation_count}"
        self._emit_status("typing", f"Model rotated (#{self._model_rotation_count}). Ready to send prompt.")

        # 5. Check if [Retry] button is present in the chat pane and click it
        retry_clicked = False
        try:
            import uiautomation as auto
            window = auto.ControlFromHandle(hwnd)
            if window and window.Exists(1, 0.2):
                doc = window.DocumentControl(searchDepth=8)
                if doc.Exists(0.5, 0.1):
                    retry_btn = doc.ButtonControl(searchDepth=14, Name="Retry")
                    if retry_btn.Exists(0.4, 0.1):
                        retry_btn.Click(waitTime=0.2)
                        retry_clicked = True
                        logger.info("Clicked [Retry] button on Quota Exceeded banner after rotating model!")
                        self._log("Clicked [Retry] button in Google AI Studio to rerun with new model", "info")
        except Exception as e:
            logger.debug(f"UIA Retry search: {e}")

        if not retry_clicked:
            retry_clicked = bool(self.find_and_click_ocr_target(["retry"], region_filter=(0.10, 0.45, 0.40, 0.85), hwnd=hwnd))
            if retry_clicked:
                self._log("Clicked [Retry] button via OCR to rerun with new model", "info")

        return True

    def republish_and_test_ai_studio(self, hwnd=None) -> bool:
        """
        Publishes/Republishes the Google AI Studio app and leaves the browser on AI Studio.
        """
        if get_playwright_manager:
            try:
                pw = get_playwright_manager(self.browser_session_id)
                if not pw.is_connected():
                    pw.ensure_page()
                if pw.is_connected():
                    state = pw.get_chat_status()
                    if not state.get("is_ai_studio") or not state.get("chat_ready"):
                        self._emit_status("error", "Republish requires an open Google AI Studio chat screen.")
                        return False
                    self._emit_status("waiting", "Publishing or republishing from the AI Studio publish panel...")
                    success = pw.republish_and_test()
                    if success:
                        self._emit_status("done", "✅ AI Studio publish/republish completed. The publish panel remains open.")
                    else:
                        self._emit_status("error", "AI Studio publish/republish did not confirm a completed deployment.")
                    return success
            except Exception as e:
                logger.warning(f"Playwright publish action failed, attempting UIA fallback: {e}")

        import ctypes
        import time
        import pyautogui
        user32 = ctypes.windll.user32

        if hwnd is None:
            hwnd = self._find_editor_window()
        if not hwnd:
            logger.warning("Google AI Studio window not found for republish")
            return False

        # 1. Bring window to front
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        time.sleep(0.2)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)

        self._emit_status("waiting", "🚀 Initiating project publication in Google AI Studio...")
        self._log("Initiating project publication in Google AI Studio...", "info")

        def click_named_control(name):
            try:
                import uiautomation as auto
                window = auto.ControlFromHandle(hwnd)
                if not window or not window.Exists(0.5, 0.1):
                    return False
                doc = window.DocumentControl(searchDepth=8)
                if not doc.Exists(0.5, 0.1):
                    return False
                for factory in (doc.ButtonControl, doc.HyperlinkControl):
                    control = factory(searchDepth=16, Name=name)
                    if control.Exists(0.2, 0.1):
                        control.Click(waitTime=0.2)
                        logger.info(f"UIA clicked publish flow control: {name}")
                        return True
            except Exception as e:
                logger.debug(f"UIA publish control '{name}': {e}")
            return False

        def control_exists(name):
            try:
                import uiautomation as auto
                window = auto.ControlFromHandle(hwnd)
                if not window or not window.Exists(0.3, 0.1):
                    return False
                doc = window.DocumentControl(searchDepth=8)
                if not doc.Exists(0.3, 0.1):
                    return False
                return any(factory(searchDepth=16, Name=name).Exists(0.1, 0.05)
                           for factory in (doc.ButtonControl, doc.HyperlinkControl, doc.TextControl))
            except Exception:
                return False

        def click_ocr(names):
            return bool(self.find_and_click_ocr_target(
                names, region_filter=(0.62, 0.99, 0.12, 0.78), hwnd=hwnd
            ))

        def api_usage_step_visible():
            return control_exists("Control Gemini API usage") or bool(
                self.find_and_click_ocr_target(
                    ["Control Gemini API usage"],
                    region_filter=(0.62, 0.99, 0.10, 0.40),
                    hwnd=hwnd,
                    click=False,
                )
            )

        # Try the actual sidebar action first. Clicking the toolbar Publish tab while
        # its panel is already open can close it and leave the action untouched.
        action_started = click_named_control("Republish") or click_ocr(["republish"])
        if not action_started:
            action_started = click_named_control("Publish your app") or click_ocr(["publish your app"])
        if not action_started and api_usage_step_visible():
            action_started = click_named_control("Continue") or click_ocr(["continue"])

        if not action_started:
            # Open the panel only when no panel action or wizard control was found.
            header_clicked = click_named_control("Publish")
            if not header_clicked:
                header_clicked = click_ocr(["publish"])
            if header_clicked:
                time.sleep(1.0)
                action_started = (
                    click_named_control("Republish")
                    or click_ocr(["republish"])
                    or click_named_control("Publish your app")
                    or click_ocr(["publish your app"])
                    or (api_usage_step_visible() and
                        (click_named_control("Continue") or click_ocr(["continue"])))
                )

        if not action_started:
            self._emit_status("error", "Could not find Republish, Continue, or Publish your app in the AI Studio publish panel.")
            return False

        # AI Studio may insert the API usage step before its Final touches screen.
        for _ in range(3):
            if api_usage_step_visible() and (click_named_control("Continue") or click_ocr(["continue"])):
                time.sleep(0.8)
                continue
            if click_named_control("Publish your app") or click_ocr(["publish your app"]):
                action_started = True
                time.sleep(0.8)
                continue
            break

        self._emit_status("waiting", "🚀 Publish/republish submitted. Waiting for deployment to finish...")
        self._log("Publish/republish submitted. Waiting for deployment status...", "info")

        stable_ready = 0
        for wait_attempt in range(90):
            in_progress = any(control_exists(label) for label in ("In progress", "Building", "Deploying", "Publishing"))
            republish_ready = control_exists("Republish")
            if republish_ready and not in_progress and wait_attempt >= 4:
                stable_ready += 1
                if stable_ready >= 2:
                    msg = "AI Studio app publish/republish completed; left on the publish panel."
                    self._emit_status("done", f"✅ {msg}")
                    self._log(msg, "success")
                    return True
            else:
                stable_ready = 0
            time.sleep(1.0)

        self._emit_status("error", "AI Studio did not confirm that the deployment finished.")
        self._log("Publish/republish was not confirmed before the timeout.", "error")
        return False

    def _send_via_web_uia(self, prompt: str, hwnd=None) -> str:
        """
        Reliable prompt injection into Google AI Studio via Windows UI Automation.

        Strategy (in order of preference):
        1. Use UIA to walk the accessibility tree and find the actual chat input element
           (contenteditable div in Firefox exposes as EditControl or DocumentControl child)
        2. If UIA finds an element → click its bounding rect center + paste + Ctrl+Enter
        3. If UIA can't find it → fall back to safe coordinate zones: try 4 positions in the
           left chat pane working from bottom-up, clicking each and testing if typing registers
        No blind Tab/Enter/Space fallback (those caused misclicks on + upload buttons).
        """
        import ctypes
        import time
        import pyautogui
        pyautogui.FAILSAFE = False
        user32 = ctypes.windll.user32

        if hwnd is None:
            hwnd = self._find_editor_window()
        if not hwnd:
            return self._web_uia_fallback(prompt, hwnd)

        # 1. Bring window to front and maximize
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)

        self._emit_status("typing", "Typing prompt into Google AI Studio...")

        # 2. Fast check: active generation check without heavy OCR
        gen_check = self._check_google_ai_studio_generation(hwnd, allow_ocr=False)
        if gen_check.get("is_generating"):
            r_text = gen_check.get("running_text") or "ongoing generation"
            self._log(f"Previous conversation is still generating ({r_text}). Waiting...", "info")
            self._emit_status("waiting", f"Waiting for active generation to finish ({r_text})...")
            wait_res = self._wait_for_google_ai_studio_completion(hwnd)
            if wait_res == "cancelled":
                return "⏹ Wait cancelled"
            elif wait_res == "retry_with_new_model":
                return self._send_via_web_uia(prompt, hwnd)
            elif wait_res and wait_res.startswith("error:"):
                return f"❌ {wait_res}"

        # 3. Get window geometry
        win_rect = self._get_window_rect(hwnd)
        if not win_rect:
            w_left, w_top, w_width, w_height = 0, 0, 1280, 800
        else:
            w_left, w_top = win_rect[0], win_rect[1]
            w_width = win_rect[2] - win_rect[0]
            w_height = win_rect[3] - win_rect[1]

        # 4. Deep UIA scan for the prompt input area
        # In Firefox, the Google AI Studio contenteditable div is exposed as an
        # EditControl or a DocumentControl descendant with specific names.
        input_rect = None
        try:
            import uiautomation as auto
            auto.SetGlobalSearchTimeout(0.3)
            win_ctrl = auto.ControlFromHandle(hwnd)
            if win_ctrl and win_ctrl.Exists(0.3, 0.05):
                # Keywords that identify the AI Studio chat input in different views
                prompt_keywords = [
                    "make changes", "ask for anything", "prompt", "message",
                    "type a message", "send a message", "chat", "input"
                ]

                def _scan_for_input(ctrl, max_depth=12):
                    """BFS over UIA tree looking for an editable input matching prompt keywords."""
                    from collections import deque
                    queue = deque([(ctrl, 0)])
                    best = None
                    while queue:
                        node, depth = queue.popleft()
                        if depth > max_depth:
                            continue
                        try:
                            ctrl_type = node.ControlTypeName
                            name = (node.Name or "").lower()
                            is_edit = ctrl_type in ("EditControl", "DocumentControl")
                            # Check if it's a visible edit-like element with prompt keywords
                            if is_edit:
                                try:
                                    r = node.BoundingRectangle
                                    if r and r.width > 100 and r.height > 20:
                                        if any(kw in name for kw in prompt_keywords):
                                            best = r
                                            return best  # Exact match, stop
                                        elif not best:
                                            # Accept any sufficiently large edit in left pane
                                            if r.left < w_left + w_width * 0.55:
                                                best = r
                                except Exception:
                                    pass
                            # Recurse into children
                            try:
                                children = node.GetChildren()
                                for child in children:
                                    queue.append((child, depth + 1))
                            except Exception:
                                pass
                        except Exception:
                            continue
                    return best

                input_rect = _scan_for_input(win_ctrl)
                if input_rect:
                    logger.info(f"UIA found prompt input element at rect: ({input_rect.left},{input_rect.top},{input_rect.width}x{input_rect.height})")
        except Exception as e:
            logger.debug(f"UIA tree scan error: {e}")

        # 5. Compute click target
        if input_rect and input_rect.width > 100:
            # Hit the center of the actual element found in the tree
            click_x = input_rect.left + int(input_rect.width * 0.45)
            click_y = input_rect.top + int(input_rect.height * 0.5)
            logger.info(f"Using UIA element coords: ({click_x}, {click_y})")
        else:
            # Fallback: try multiple coordinate zones in the left chat pane
            # AI Studio App Builder: left ~44% pane, textarea near bottom
            # Try 4 positions from bottom-up (110px, 140px, 170px, 200px above bottom)
            chat_pane_x = w_left + int(w_width * 0.22)  # Center of left 44% pane
            candidate_ys = [
                w_top + w_height - 110,
                w_top + w_height - 140,
                w_top + w_height - 170,
                w_top + w_height - 200,
            ]
            click_x = chat_pane_x
            click_y = candidate_ys[0]
            logger.info(f"No UIA element found. Using coordinate fallback: ({click_x}, {click_y})")

        # 6. Dismiss any popup/modal
        self._press_key("escape")
        time.sleep(0.1)

        # 7. Click the prompt area
        logger.info(f"Clicking prompt input at ({click_x}, {click_y})")
        pyautogui.click(click_x, click_y)
        time.sleep(0.15)

        # 8. Clear existing text and paste prompt
        self._press_hotkey("ctrl+a")
        time.sleep(0.05)
        self._press_key("backspace")
        time.sleep(0.05)

        self._clipboard_set(prompt)
        time.sleep(0.1)
        self._press_hotkey("ctrl+v")
        time.sleep(0.15)

        # Trigger reactive framework change event
        self._press_key("space")
        time.sleep(0.03)
        self._press_key("backspace")
        time.sleep(0.08)

        # 9. Submit via Ctrl+Enter
        logger.info("Submitting via Ctrl+Enter...")
        self._press_hotkey("ctrl+enter")
        time.sleep(0.25)

        # 10. Also click the Send button (↑ arrow) located bottom-right of left chat pane
        # Use UIA to find it precisely, else compute from geometry
        send_clicked = False
        try:
            import uiautomation as auto
            win_ctrl = auto.ControlFromHandle(hwnd)
            if win_ctrl and win_ctrl.Exists(0.2, 0.05):
                for btn_label in ["Send", "Send prompt", "arrow_upward", "Submit"]:
                    btn = win_ctrl.ButtonControl(searchDepth=10, Name=btn_label)
                    if btn and btn.Exists(0.2, 0.05):
                        r = btn.BoundingRectangle
                        if r and r.width > 10:
                            pyautogui.click(r.left + r.width // 2, r.top + r.height // 2)
                            send_clicked = True
                            logger.info(f"Clicked Send button via UIA at ({r.left + r.width//2}, {r.top + r.height//2})")
                            break
        except Exception:
            pass

        if not send_clicked:
            # Coordinate fallback for send button: bottom-right of left chat pane
            chat_right = w_left + int(w_width * 0.44)
            send_x = chat_right - 40
            send_y = w_top + w_height - 45
            logger.info(f"Clicking Send button (coord fallback) at ({send_x}, {send_y})")
            pyautogui.click(send_x, send_y)

        time.sleep(0.2)
        return f"✅ Prompt injected and submitted into Google AI Studio ({len(prompt)} chars)"


    def _web_uia_fallback(self, prompt: str, hwnd=None) -> str:
        """Robust fallback: focuses chat textarea, pastes, dispatches Enter, Ctrl+Enter, and clicks Send button."""
        import pyautogui
        pyautogui.FAILSAFE = False
        import ctypes
        user32 = ctypes.windll.user32

        win_rect = self._get_window_rect(hwnd) if hwnd else None
        if win_rect:
            w_left, w_top, w_right, w_bottom = win_rect
            w_width = w_right - w_left
            w_height = w_bottom - w_top
        else:
            w_left, w_top, w_width, w_height = 0, 0, 1200, 800

        if hwnd:
            try:
                user32.ShowWindow(hwnd, 3)
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.3)
            except Exception:
                pass

        # 1. Click into Chat input area (~35% from left, ~85px from bottom)
        input_x = w_left + int(w_width * 0.35)
        input_y = w_top + w_height - 85
        logger.info(f"Fallback: Clicking chat input area at ({input_x}, {input_y})")
        pyautogui.click(input_x, input_y)
        time.sleep(0.4)

        try:
            import uiautomation as auto
            root = auto.GetRootControl()
            dialog = root.TextControl(searchDepth=14, Name="Select or upload a file")
            if dialog.Exists(0.2, 0.05):
                logger.warning("Fallback accidentally opened file upload dialog. Closing it and shifting click right.")
                self._press_key("escape")
                time.sleep(0.4)
                input_x += 180
                pyautogui.click(input_x, input_y)
                time.sleep(0.2)
        except Exception:
            pass
        # 2. Clear existing text
        self._press_hotkey("ctrl+a")
        time.sleep(0.08)
        self._press_key("backspace")
        time.sleep(0.08)

        # 3. Paste prompt
        self._clipboard_set(prompt)
        time.sleep(0.15)
        self._press_hotkey("ctrl+v")
        time.sleep(0.3)

        # 4. Trigger input change event
        self._press_key("space")
        time.sleep(0.05)
        self._press_key("backspace")
        time.sleep(0.2)

        # 5. SUBMIT VIA ENTER
        logger.info("Fallback: Pressing Enter...")
        self._press_key("enter")
        time.sleep(0.3)

        # 6. SUBMIT VIA CTRL+ENTER
        logger.info("Fallback: Pressing Ctrl+Enter...")
        self._press_hotkey("ctrl+enter")
        time.sleep(0.3)

        # 7. CLICK SEND BUTTON ICON (.send-button at ~38% width, ~65px from bottom)
        send_x = w_left + int(w_width * 0.38)
        send_y = w_top + w_height - 65
        logger.info(f"Fallback: Clicking Send button icon at ({send_x}, {send_y})")
        pyautogui.click(send_x, send_y)
        time.sleep(0.4)

        # 8. TAB + ENTER (Fallback for when coordinates miss and Ctrl+Enter fails)
        logger.info("Fallback: Pressing Tab then Enter (to target Send button)...")
        self._press_key("tab")
        time.sleep(0.1)
        self._press_key("enter")
        time.sleep(0.1)
        self._press_key("space")
        time.sleep(0.3)

        return f"✅ Prompt injected and submitted into Google AI Studio ({len(prompt)} chars)"

    def _get_window_rect(self, hwnd: Optional[int]) -> Optional[Tuple[int, int, int, int]]:
        """Get window bounding rectangle (left, top, right, bottom) via Win32 API.
        Returns (left, top, right, bottom) tuple or None if unavailable.
        """
        if not hwnd:
            return None
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return (rect.left, rect.top, rect.right, rect.bottom)
        except Exception as e:
            logger.debug(f"Error getting window rect for hwnd {hwnd}: {e}")
        return None

    def _find_editor_window(self) -> Optional[int]:
        """Find and reserve one visible editor window for this workflow bridge."""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32

            search_terms = self._get_window_keywords()
            if not search_terms:
                return None

            EnumWindowsProc = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )

            title_matches = []

            def enum_callback(hwnd, lparam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value
                        for term in search_terms:
                            if term.lower() in title.lower():
                                title_matches.append(int(hwnd))
                                break
                return True

            user32.EnumWindows(EnumWindowsProc(enum_callback), 0)
            candidates = title_matches
            if not candidates:
                pids = set(self._get_editor_pids())
                if not pids:
                    return None

                def enum_pid_callback(hwnd, lparam):
                    if user32.IsWindowVisible(hwnd):
                        pid = wintypes.DWORD()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        if pid.value in pids:
                            candidates.append(int(hwnd))
                    return True

                user32.EnumWindows(EnumWindowsProc(enum_pid_callback), 0)

            if not candidates:
                return None
            session = self.browser_session_id
            with self._window_assignment_lock:
                previous = self._window_assignments.get(session)
                used = {hwnd for owner, hwnd in self._window_assignments.items() if owner != session}
                if previous in candidates and previous not in used and user32.IsWindowVisible(previous):
                    return previous
                selected = next((hwnd for hwnd in candidates if hwnd not in used), candidates[0])
                self._window_assignments[session] = selected
                return selected

        except Exception as e:
            logger.debug(f"Could not find editor window: {e}")
            return None

    def _interaction_lock(self, hwnd=None):
        key = ("hwnd", int(hwnd)) if hwnd else ("editor", self._editor)
        with self._window_assignment_lock:
            if key not in self._interaction_locks:
                self._interaction_locks[key] = threading.RLock()
            return self._interaction_locks[key]

    def _get_window_title(self, hwnd) -> str:
        """Get the current title of a window"""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                return buff.value
        except Exception:
            pass
        return ""

    def _get_window_keywords(self) -> List[str]:
        keywords = {
            "antigravity": ["Antigravity", "antigravity"],
            "windsurf": ["Windsurf", "windsurf"],
            "windsurf_next": ["Windsurf Next", "windsurf-next", "Windsurf", "windsurf"],
            "cursor": ["Cursor", "cursor"],
            "vscode": ["Visual Studio Code", "Code"],
            "codex": ["Codex", "codex"],
            "google_ai_studio": ["Google AI Studio", "Gemini", "aistudio", "AI Studio"],
        }
        override = os.getenv(f"{self._editor.upper()}_WINDOW_KEYWORDS")
        if override:
            return [item.strip() for item in override.split(",") if item.strip()]
        return keywords.get(self._editor, [])

    def _get_process_names(self) -> List[str]:
        override = os.getenv(f"{self._editor.upper()}_PROCESS_NAMES")
        if override:
            return [item.strip() for item in override.split(",") if item.strip()]
        return self.EDITORS[self._editor].get("process_names", [])

    def _get_editor_pids(self) -> List[int]:
        process_names = self._get_process_names()
        if not process_names:
            return []

        try:
            import csv
            output = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"],
                shell=True, text=True, stderr=subprocess.DEVNULL
            )
            pids = []
            for row in csv.reader(output.splitlines()):
                if len(row) < 2:
                    continue
                image_name = row[0]
                pid_str = row[1]
                for pname in process_names:
                    if pname.lower() == image_name.lower():
                        try:
                            pids.append(int(pid_str))
                        except ValueError:
                            pass
            return pids
        except Exception:
            return []

    def _wait_for_completion(self) -> str:
        """Wait for the AI conversation to finish.
        Returns: 'done', 'timeout', or 'cancelled'

        Detection strategy:
        1. Check if editor window title contains 'thinking/generating' keywords
        2. Monitor editor process CPU -- high CPU = still working
        3. When title stabilizes AND CPU drops, conversation is done
        4. Fallback: timeout after _completion_timeout seconds
        """
        editor_config = self.EDITORS[self._editor]
        thinking_keywords = editor_config.get("thinking_keywords", [])
        start_time = time.time()

        hwnd = self._find_editor_window()

        # Dedicated smart wait for Google AI Studio (prevents premature exit while AI is still generating)
        if self._editor == "google_ai_studio":
            return self._wait_for_google_ai_studio_completion(hwnd)

        # Wait a moment for the AI to start processing
        time.sleep(3.0)

        # Track title stability: must be stable for N consecutive checks
        stable_count = 0
        required_stable = 3  # must be stable for 3 x poll_interval
        last_title = ""
        was_thinking = False

        while True:
            elapsed = time.time() - start_time

            # check for popups and allow them
            clicked_popup = self._check_and_allow()
            if clicked_popup:
                # We just clicked "Run" or "Allow". Reserving time for the terminal to launch.
                stable_count = 0
                time.sleep(1.0)
                continue

            # Check cancel
            if self._cancel_wait.is_set():
                return "cancelled"

            # Check timeout
            if elapsed >= self._completion_timeout:
                return "timeout"

            # --- Detection Logic ---
            
            detail_parts = []
            
            # Use strict visual detection if we are using antigravity
            if self._editor == "antigravity":
                is_generating_visually = self.visual_detector.is_generating(hwnd)
                if is_generating_visually:
                    detail_parts.append("🔴 Image: Generating")
                    is_thinking = True
                    was_thinking = True
                    stable_count = 0  # reset stability since it's definitely working
                else:
                    state = self.visual_detector._last_state
                    if state == "ready_blue":
                        detail_parts.append("🔵 Image: Ready (Text)")
                        # If we see the blue arrow, it is definitely done generating
                        is_thinking = False
                        # Removed the artificial stable_count accelerator here!
                        # The "Run Alt+Enter" button is ALSO blue. Accelerating here caused the bug where
                        # the script thought it was finished when a "Run" prompt simply appeared.
                    elif state == "ready_empty":
                        detail_parts.append("⚪ Image: Ready (Empty)")
                        is_thinking = False
                    else:
                        detail_parts.append("Image Check Failed")

            current_title = ""
            if hwnd:
                current_title = self._get_window_title(hwnd)

            # Check if title shows thinking/generating (Fallback/Augment)
            if self._editor != "antigravity" or self.visual_detector._last_state == "unknown":
                is_thinking = False
                for kw in thinking_keywords:
                    if kw.lower() in current_title.lower():
                        is_thinking = True
                        was_thinking = True
                        break

            # Check process CPU usage (Fallback/Augment)
            cpu_busy = False
            if self._editor != "antigravity" or self.visual_detector._last_state == "unknown":
                if self._editor != "google_ai_studio":
                    cpu_busy = self._is_editor_cpu_busy()

            # Web DOM Explicit Check (Google AI Studio)
            if self._editor == "google_ai_studio":
                # Check for active errors (filtering out historical errors from scrollback)
                web_errors = self.detect_google_ai_studio_errors(hwnd)
                pre_errors = getattr(self, "_pre_prompt_errors", set())
                new_errors = [e for e in web_errors if e not in pre_errors]
                if new_errors:
                    err_msg = " | ".join(new_errors)
                    is_quota = any(k in err_msg.lower() for k in ["quota", "exhausted", "rate limit", "overloaded", "resource has been exhausted", "try again later"])
                    if is_quota and getattr(self, "auto_rotate_model", True):
                        self._emit_status("typing", "Quota exceeded. Switching to another available model...")
                        logger.warning(f"Quota error detected: {err_msg}. Triggering model rotation...")
                        rotated = self.rotate_google_ai_studio_model(hwnd)
                        if rotated:
                            return "retry_with_new_model"

                    self._emit_status("error", f"❌ AI Studio Error: {err_msg}")
                    return f"error: {err_msg}"

                # Override title/CPU checks with true Web DOM reflection
                is_thinking = self._is_web_generating(hwnd)
                if is_thinking:
                    was_thinking = True
                    stable_count = 0

            # Status update
            if is_thinking and not "🔴 Image: Generating" in detail_parts:
                detail_parts.append("AI is thinking")
            if cpu_busy:
                detail_parts.append("high CPU")
            detail_parts.append(f"{int(elapsed)}s elapsed")
            self._emit_status("waiting", f"🔵 {' | '.join(detail_parts)}")

            # If NOT thinking AND CPU is low AND title is stable
            if not is_thinking and not cpu_busy:
                if current_title == last_title:
                    stable_count += 1
                else:
                    stable_count = 0

                # Require either: was_thinking and now stable, OR stable for longer
                if was_thinking and stable_count >= required_stable:
                    return "done"
                elif stable_count >= (required_stable + 3):  # extra patience if we never saw thinking
                    return "done"
            else:
                stable_count = 0

            last_title = current_title

            if self._cancel_wait.wait(timeout=self._poll_interval):
                return "cancelled"

    def _get_chat_ocr_lines(self, hwnd=None) -> List[str]:
        """Runs fast local WinRT OCR on the left chat pane of the Google AI Studio window."""
        import tempfile
        import pyautogui

        if hwnd is None:
            hwnd = self._find_editor_window()
        if not hwnd:
            return []

        win_rect = self._get_window_rect(hwnd)
        if not win_rect:
            return []

        w_left, w_top, w_right, w_bottom = win_rect
        w_width = w_right - w_left
        w_height = w_bottom - w_top
        if w_width <= 100 or w_height <= 100:
            return []

        # Crop strictly to the chat pane (left ~45% of browser window)
        chat_w = int(w_width * 0.45)
        bbox = (w_left, w_top, chat_w, w_height)

        temp_img = None
        try:
            img = pyautogui.screenshot(region=bbox)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                temp_img = tf.name
            img.save(temp_img)

            script_dir = os.path.dirname(os.path.abspath(__file__))
            ocr_script = os.path.join(script_dir, "ocr_helper.ps1")
            if not os.path.exists(ocr_script):
                return []

            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", ocr_script,
                temp_img
            ]
            res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=6)
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout, strict=False)
                lines = [l.get("text", "").strip() for l in data.get("lines", []) if l.get("text", "").strip()]
                return lines
        except Exception as e:
            logger.debug(f"OCR chat lines error: {e}")
        finally:
            if temp_img and os.path.exists(temp_img):
                try:
                    os.remove(temp_img)
                except Exception:
                    pass
        return []

    def _check_google_ai_studio_generation(self, hwnd=None, allow_ocr: bool = False) -> Dict[str, Any]:
        """
        Scans Google AI Studio chat screen to determine active generation status.
        Fast by default (depth <= 6); OCR is opt-in to eliminate background CPU spikes.
        """
        if get_playwright_manager:
            try:
                pw = get_playwright_manager(self.browser_session_id)
                if pw.is_connected():
                    pw_gen = pw.is_generating()
                    is_gen = pw_gen.get("is_generating", False)
                    status_text = pw_gen.get("status_text", "")
                    return {
                        "is_generating": is_gen,
                        "is_finished": not is_gen,
                        "running_text": status_text if is_gen else "",
                        "ran_text": status_text if not is_gen else "",
                        "has_stop_btn": pw_gen.get("has_stop_btn", False),
                        "has_send_btn": pw_gen.get("has_send_btn", False),
                    }
            except Exception as e:
                logger.debug(f"Playwright is_generating error: {e}")

        if hwnd is None:
            hwnd = self._find_editor_window()

        info = {
            "is_generating": False,
            "is_finished": False,
            "running_text": "",
            "ran_text": "",
            "has_stop_btn": False,
            "has_send_btn": False,
        }
        if not hwnd:
            return info

        # --- 1. Fast UIA DOM Inspection ---
        try:
            import uiautomation as auto
            window = auto.ControlFromHandle(hwnd)
            if not window or not window.Exists(0.3, 0.1):
                window = auto.WindowControl(searchDepth=1, handle=hwnd)

            if window and window.Exists(0.3, 0.1):
                doc = window.DocumentControl(searchDepth=6)
                if doc and doc.Exists(0.3, 0.1):
                    doc_rect = doc.BoundingRectangle
                    chat_right = (doc_rect.left + int(doc_rect.width * 0.45)) if doc_rect else 999999
                    chat_bottom = doc_rect.bottom if doc_rect else 999999

                    nodes_scanned = 0
                    def scan_node(ctrl, depth=0):
                        nonlocal nodes_scanned
                        if depth > 6 or nodes_scanned > 60:
                            return
                        try:
                            nodes_scanned += 1
                            rect = ctrl.BoundingRectangle
                            # Restrict search strictly to the chat screen (left ~45%)
                            if rect and rect.left > chat_right + 40:
                                return

                            name = (ctrl.Name or "").strip()
                            name_lower = name.lower()
                            help_lower = (ctrl.HelpText or "").lower()
                            c_type = ctrl.ControlTypeName

                            # 1. "Running for <N>s" indicator
                            if "running for" in name_lower or "running for" in help_lower:
                                info["is_generating"] = True
                                info["running_text"] = name or "Running for"
                            elif "ran for" in name_lower or "ran for" in help_lower:
                                info["ran_text"] = name or "Ran for"
                                info["is_finished"] = True

                            # 2. Stop Button in chat input area
                            if c_type in ("ButtonControl", "Button"):
                                if any(s in name_lower or s in help_lower for s in ["stop", "stop generating", "stop generation", "cancel"]):
                                    if rect and rect.bottom >= chat_bottom - 180:
                                        info["has_stop_btn"] = True
                                        info["is_generating"] = True
                                elif any(s in name_lower or s in help_lower for s in ["send", "arrow_upward_alt", "↑", "submit"]):
                                    if rect and rect.bottom >= chat_bottom - 180:
                                        info["has_send_btn"] = True

                            # 3. Text/Icon controls representing stop
                            if ("stop" in name_lower or "cancel" in name_lower) and c_type in ("TextControl", "Text", "ImageControl", "Image"):
                                if rect and rect.bottom >= chat_bottom - 180:
                                    info["has_stop_btn"] = True
                                    info["is_generating"] = True

                            for child in ctrl.GetChildren():
                                scan_node(child, depth + 1)
                        except Exception:
                            pass

                    scan_node(doc)
        except Exception as e:
            logger.debug(f"UIA generation check error: {e}")

        # --- 2. OCR Fallback ONLY if explicitly allowed ---
        if not info["is_generating"] and not info["is_finished"] and allow_ocr:
            try:
                ocr_lines = self._get_chat_ocr_lines(hwnd)
                for line in ocr_lines:
                    t = line.lower()
                    is_model_header = any(m in t for m in ["gemin", "flash", "pro", "2.5", "2.0", "1.5"])
                    if "running for" in t or ("running" in t and "for" in t) or ("rurnnq" in t) or ("rurning" in t) or (is_model_header and any(r in t for r in ["rurn", "runn", "running"])):
                        info["is_generating"] = True
                        info["running_text"] = line
                        break
                    elif "ran for" in t or ("ran" in t and "for" in t) or (is_model_header and "ran" in t):
                        info["ran_text"] = line
                        info["is_finished"] = True
            except Exception as e:
                logger.debug(f"OCR generation check error: {e}")

        return info

    def _is_web_generating(self, hwnd=None) -> bool:
        """Dynamically check if Google AI Studio is currently generating."""
        gen_state = self._check_google_ai_studio_generation(hwnd)
        return bool(gen_state.get("is_generating", False))

    def _wait_for_google_ai_studio_completion(self, hwnd=None) -> str:
        """
        Specialized completion tracker for Google AI Studio.
        
        Guarantees:
        1. Keeps waiting ('adds delay') as long as the AI conversation is running.
        2. Detects true completion or pre-ended conversations immediately without wasting time.
        3. Automatically detects quota errors and selects another available model.
        """
        if get_playwright_manager:
            try:
                pw = get_playwright_manager(self.browser_session_id)
                if pw.is_connected():
                    logger.info("Waiting for Google AI Studio completion directly via Playwright DOM...")
                    return pw.wait_for_completion(
                        timeout_s=max(getattr(self, "_completion_timeout", 300), 900),
                        status_callback=self._emit_status,
                        cancel_event=self._cancel_wait,
                        auto_rotate=getattr(self, "auto_rotate_model", True),
                    )
            except Exception as e:
                logger.warning(f"Playwright completion wait failed: {e}. Falling back to visual/UIA tracker.")

        start_time = time.time()
        was_generating = False
        initial_grace_period = 4.0  # seconds to let request reach server & UI update
        timeout_limit = max(getattr(self, "_completion_timeout", 300), 900)  # 15 mins for large coding tasks
        poll_interval = getattr(self, "_poll_interval", 1.5)
        stable_idle_count = 0

        self._emit_status("waiting", "🔵 AI processing: Monitoring generation status...")
        logger.info("Starting Google AI Studio smart completion monitoring...")

        time.sleep(1.5)
        last_ocr_time = time.time()

        while True:
            elapsed = time.time() - start_time

            # 1. User cancellation
            if self._cancel_wait.is_set():
                logger.info("Google AI Studio wait cancelled by user")
                return "cancelled"

            # 2. Timeout check (generous 15m limit, extended while active)
            if elapsed >= timeout_limit:
                logger.warning(f"Google AI Studio wait timed out after {timeout_limit}s")
                return "timeout"

            # 3. Error detection & Auto-rotation (throttled OCR every 8s to prevent CPU freeze)
            should_ocr = (time.time() - last_ocr_time >= 8.0)
            web_errors = self.detect_google_ai_studio_errors(hwnd, allow_ocr=should_ocr)
            pre_errors = getattr(self, "_pre_prompt_errors", set())
            new_errors = [e for e in web_errors if e not in pre_errors]
            if new_errors:
                err_msg = " | ".join(new_errors)
                is_quota = any(k in err_msg.lower() for k in [
                    "quota", "exhausted", "rate limit", "overloaded", "resource has been exhausted", "try again later"
                ])
                if is_quota and getattr(self, "auto_rotate_model", True):
                    self._emit_status("typing", "Quota exceeded. Switching to another available model...")
                    logger.warning(f"Quota error detected during generation: {err_msg}. Rotating model...")
                    rotated = self.rotate_google_ai_studio_model(hwnd)
                    if rotated:
                        return "retry_with_new_model"

                self._emit_status("error", f"❌ AI Studio Error: {err_msg}")
                return f"error: {err_msg}"

            # 4. Check dynamic generation state (throttled OCR)
            gen_state = self._check_google_ai_studio_generation(hwnd, allow_ocr=should_ocr)
            if should_ocr:
                last_ocr_time = time.time()
            is_generating = gen_state.get("is_generating", False)
            running_text = gen_state.get("running_text", "")
            ran_text = gen_state.get("ran_text", "")
            has_send = gen_state.get("has_send_btn", False)
            has_stop = gen_state.get("has_stop_btn", False)

            if is_generating:
                was_generating = True
                stable_idle_count = 0
                desc = running_text or f"Running for {int(elapsed)}s"
                self._emit_status("waiting", f"🔵 AI is generating ({desc})")
                logger.debug(f"Google AI Studio actively generating: {desc}")
            else:
                # Generation is not currently active
                if was_generating:
                    # Case A: Was generating, and NOW stopped (completed or pre-ended!)
                    finish_label = ran_text or f"Finished in {int(elapsed)}s"
                    self._log(f"Google AI Studio generation complete: {finish_label}", "success")
                    self._emit_status("waiting", f"✅ Generation finished ({finish_label}). Advancing...")
                    logger.info(f"Google AI Studio completed: {finish_label}. Advancing without delay.")
                    time.sleep(1.5)  # Brief settling delay ("start without wasting time: be smart")
                    return "done"
                else:
                    # Case B: Was not yet marked generating
                    if elapsed < initial_grace_period:
                        self._emit_status("waiting", f"🔵 AI starting generation ({int(elapsed)}s)...")
                    else:
                        # Beyond grace period: check if already completed or idle
                        if ran_text:
                            # Check if "Ran for 0s" — this usually means error (Invalid argument, etc.)
                            if "ran for 0s" in ran_text.lower() or "ran for 0 s" in ran_text.lower():
                                # Re-check for errors since 0s completion usually means the API rejected the request
                                web_errors = self.detect_google_ai_studio_errors(hwnd)
                                pre_errors = getattr(self, "_pre_prompt_errors", set())
                                new_errors = [e for e in web_errors if e not in pre_errors]
                                if new_errors:
                                    err_msg = " | ".join(new_errors)
                                    self._emit_status("error", f"\u274c AI Studio Error: {err_msg}")
                                    return f"error: {err_msg}"
                            # Finished very quickly
                            self._log(f"Google AI Studio generation complete: {ran_text}", "success")
                            time.sleep(1.0)
                            return "done"
                        elif has_send and not has_stop:
                            stable_idle_count += 1
                            if stable_idle_count >= 3:
                                logger.info(f"Google AI Studio confirmed idle and ready ({int(elapsed)}s)")
                                time.sleep(1.0)
                                return "done"
                        else:
                            stable_idle_count = 0
                            self._emit_status("waiting", f"🔵 Waiting for AI response ({int(elapsed)}s)...")

            # Polling delay
            if self._cancel_wait.wait(timeout=poll_interval):
                return "cancelled"

    def _is_editor_cpu_busy(self) -> bool:
        """Check if the editor process is using significant CPU.
        Returns True if CPU usage is above threshold (suggests still working)."""
        editor_config = self.EDITORS[self._editor]
        process_names = editor_config.get("process_names", [])

        if not process_names:
            return False

        try:
            # 1. Try wmic (Old School)
            for pname in process_names:
                try:
                    output = subprocess.check_output(
                        f'wmic process where "name=\'{pname}\'" get PercentProcessorTime',
                        shell=True, text=True, stderr=subprocess.DEVNULL,
                        timeout=3,
                    )
                    for line in output.strip().split("\n"):
                        line = line.strip()
                        if line and line.isdigit():
                            cpu = int(line)
                            if cpu > 15:
                                return True
                except Exception:
                    continue

            # 2. Try PowerShell fallback (Better for Windows 10/11)
            pnames_str = ",".join([f"'{p.replace('.exe','')}'" for p in process_names])
            ps_cmd = (
                f"Get-Process -Name {pnames_str} -ErrorAction SilentlyContinue | "
                "Where-Object { $_.CPU -gt 0 } | Select-Object -ExpandProperty Name"
            )
            output = subprocess.check_output(
                ["powershell", "-Command", ps_cmd],
                shell=True, text=True, stderr=subprocess.DEVNULL,
                timeout=5
            )
            if output.strip():
                return True

        except Exception:
            pass
        return False

    def _trigger_ocr_click(self) -> bool:
        """Looks for action buttons using UI Automation first, then falls back to PyAutoGUI pixel search"""
        if not getattr(self, "use_ocr_click", True):
            return False

        # 1. Try UI Automation first (Requires --force-renderer-accessibility)
        try:
            import uiautomation as auto
            import time
            hwnd = self._find_editor_window()
            if hwnd:
                window = auto.WindowControl(searchDepth=1, handle=hwnd)
                if window.Exists(0, 0):
                    # Safely attempt to focus and scroll down the view to reveal the latest buttons
                    try:
                        window.SetFocus()
                        time.sleep(0.1)
                        window.SendKeys('{PageDown}', waitTime=0.05)
                        window.SendKeys('{PageDown}', waitTime=0.05)
                    except Exception:
                        pass

                    action_names = ["Run Alt+↵", "Allow Once", "Allow This Conversation", "Accept all", "Run", "Allow"]
                    
                    # Deep search for the specific button names (Electron wraps elements deeply)
                    for name in action_names:
                        btn = window.ButtonControl(searchDepth=12, Name=name)
                        if btn.Exists(0, 0):
                            try:
                                # Ask the UI framework to natively scroll it into view if supported
                                btn.GetScrollItemPattern().ScrollIntoView()
                            except Exception:
                                pass
                                
                            btn.Click(waitTime=0.1)
                            logger.info(f"UIA Auto-Clicked button: '{btn.Name}'")
                            return True
        except ImportError:
            pass  # Fail silently if uiautomation isn't installed
        except Exception as e:
            logger.debug(f"UIA click failed: {e}")

        # 2. Fallback to pixel color logic
        try:
            import pyautogui
            
            # Using pyautogui.screenshot() matches its own coordinate system (handles DPI scaling inherently)
            screen = pyautogui.screenshot()
            pixels = screen.load()
            width, height = screen.size
            
            # Focus on the right half of the screen
            start_x = width // 2
            
            buttons = []
            clicked = False
            
            # Sub-sample image vertically for speed
            y = 0
            while y < height:
                x = start_x
                while x < width:
                    r, g, b = pixels[x, y]
                    # Check for VS Code/Antigravity Blue background
                    # Must be decently bright, and blue must be the dominant channel over red/green.
                    if b > 120 and r < b * 0.7 and g < b * 0.9:
                        # Test if this is a solid block of blue with possible WHITE text
                        blue_count = 0
                        white_count = 0
                        total_checks = 0
                        for dy in range(0, 20, 5):
                            for dx in range(0, 60, 5):
                                sx = min(width - 1, x + dx)
                                sy = min(height - 1, y + dy)
                                sr, sg, sb = pixels[sx, sy]
                                
                                # Is it blue background?
                                if sb > 110 and sr < sb * 0.8 and sg < sb * 0.95:
                                    blue_count += 1
                                # Is it white text?
                                elif sr > 180 and sg > 180 and sb > 180:
                                    white_count += 1
                                total_checks += 1
                                
                        # Valid button: Mostly Blue + White, with at least 30% being the blue background
                        # This prevents rejecting buttons just because the white text is very large
                        if (blue_count + white_count) >= (total_checks * 0.8) and blue_count >= (total_checks * 0.3):
                            center_x = min(width - 1, x + 30)
                            center_y = min(height - 1, y + 10)
                            buttons.append((center_x, center_y))
                            
                            # Skip ahead horizontally to avoid detecting the exact same button multiple times
                            x += 160
                            continue
                    x += 10
                y += 10
            
            if buttons:
                # We prioritize the right-most and bottom-most button
                buttons.sort(key=lambda p: (p[0], p[1]), reverse=True)
                
                # DPI NORMALIZATION: Pillow screenshots are physical, pyautogui.click is logical.
                # If pyautogui.size() is 1920x1080 and screenshot is 3840x2160, scale is 2.0.
                try:
                    logical_w, logical_h = pyautogui.size()
                    scale_factor = width / logical_w
                except Exception:
                    scale_factor = 1.0
                
                pos_phys = buttons[0]
                pos_log = (pos_phys[0] / scale_factor, pos_phys[1] / scale_factor)
                
                try:
                    pyautogui.click(pos_log[0], pos_log[1])
                    clicked = True
                    logger.info(f"PIL Auto-Clicked blue button at Logical:{pos_log} (Physical:{pos_phys}, Scale:{scale_factor})")
                except Exception:
                    pass
                        
            return clicked
        except Exception as e:
            logger.debug(f"PIL click loop error: {e}")
            return False

    def _check_and_allow(self):
        """Check for common AI editor 'Allow', 'Run', or 'Confirm' buttons and interact with them"""
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # High frequency pulse
        if not hasattr(self, "_last_allow_time"):
            self._last_allow_time = 0
            
        now = time.time()
        if now - self._last_allow_time < 2.0:  # check every 2 seconds
            return
            
        self._last_allow_time = now
        
        # DOM Editors (Web Browsers) don't have modal 'Allow Workspace' prompts
        # Blasting blind keyboard shortcuts into a web browser cancels active text.
        if self._editor == "google_ai_studio":
            return False
        
        # Track title stability for CodeX smart prompt detection
        if self._editor == "codex":
            # State is now initialized in __init__
            pass
        
        # Look for the window
        hwnd = self._find_editor_window()
        if not hwnd:
            return

        # FORCE FOCUS: More robust than simple SetForegroundWindow
        try:
            foreground_hwnd = user32.GetForegroundWindow()
            if foreground_hwnd != hwnd:
                # Get thread IDs
                fore_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
                this_thread = kernel32.GetCurrentThreadId()
                
                # Attach input to bypass focus restrictions
                user32.AttachThreadInput(this_thread, fore_thread, True)
                user32.ShowWindow(hwnd, 5)  # SW_SHOW
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
                user32.AttachThreadInput(this_thread, fore_thread, False)
                time.sleep(0.1)
        except Exception:
            # Fallback to simple focus
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)

        # Pulsing logic for Blue Buttons
        # Update for CodeX: send '1' (for "Yes" option) and then 'Enter'
        # SMART DETECTION: Only pulse if title has been stable for 5+ seconds and AI isn't 'thinking'
        if self._editor == "codex":
            hwnd = self._find_editor_window()
            if not hwnd: return
            
            editor_config = self.EDITORS[self._editor]
            title = self._get_window_title(hwnd)
            is_thinking = False
            for kw in editor_config.get("thinking_keywords", []):
                if kw.lower() in title.lower():
                    is_thinking = True
                    break
            
            if not is_thinking:
                if title == self._codex_last_title and title != "":
                    if self._codex_stable_start == 0:
                        self._codex_stable_start = time.time()
                    
                    elapsed_stable = time.time() - self._codex_stable_start
                    # If stable for 5s and we haven't pulsed in the last 10s
                    if elapsed_stable > 5.0 and (time.time() - self._codex_last_pulse > 10.0):
                        logger.info(f"CodeX prompt heuristic triggered (title stable for {int(elapsed_stable)}s)")
                        self._press_key("1")
                        time.sleep(0.1)
                        self._press_key("enter")
                        self._codex_last_pulse = time.time()
                else:
                    self._codex_last_title = title
                    self._codex_stable_start = 0
            else:
                self._codex_stable_start = 0
            
            return

        # 1. OPTICAL DETECTION: Scan for blue buttons and click
        if getattr(self, "use_ocr_click", True):
            clicked = self._trigger_ocr_click()
            if clicked:
                self._last_allow_time = time.time()
                return True  # Signal to caller that we clicked something

            # 2. KEYBOARD FALLBACK: OCR found nothing visible, pulse hotkeys
            # PRIMARY: Antigravity's "Run Alt+↵" button
            self._press_hotkey("alt+enter")
            time.sleep(0.04)

            # SECONDARY: "Always allow" (Alt+A) / "Allow" (Alt+L)
            self._press_hotkey("alt+a")
            time.sleep(0.04)
            self._press_hotkey("alt+l")
            time.sleep(0.04)

            # TERTIARY: Run, Confirm, Yes
            self._press_hotkey("alt+r")
            time.sleep(0.04)
            self._press_hotkey("alt+c")
            time.sleep(0.04)
            self._press_hotkey("alt+y")
            time.sleep(0.04)

            # FALLBACKS: Plain Enter and Ctrl+Enter
            self._press_hotkey("enter")
            time.sleep(0.04)
            self._press_hotkey("ctrl+enter")

            logger.debug("Pulsed accept/allow hotkeys.")

        return False

    # ═══════════════════════════════════════════════════
    # KEYBOARD SIMULATION HELPERS
    # ═══════════════════════════════════════════════════
    def _press_hotkey(self, hotkey: str):
        """Press a hotkey combination like 'ctrl+l' or 'ctrl+shift+i'"""
        import ctypes

        VK_MAP = {
            "ctrl": 0x11, "shift": 0x10, "alt": 0x12,
            "enter": 0x0D, "tab": 0x09, "escape": 0x1B,
            "space": 0x20, "backspace": 0x08,
        }
        # Add letters a-z
        for c in "abcdefghijklmnopqrstuvwxyz":
            VK_MAP[c] = ord(c.upper())
        # Add digits 0-9
        for d in "0123456789":
            VK_MAP[d] = ord(d)
        # Add v specifically for Ctrl+V
        VK_MAP["v"] = 0x56

        KEYEVENTF_KEYUP = 0x0002
        user32 = ctypes.windll.user32

        keys = [k.strip().lower() for k in hotkey.split("+")]
        vk_codes = [VK_MAP.get(k, 0) for k in keys]

        # Press down all keys
        for vk in vk_codes:
            if vk:
                user32.keybd_event(vk, 0, 0, 0)
                time.sleep(0.02) # Small delay for reliability

        time.sleep(0.05) # Hold keys down briefly

        # Release all keys in reverse
        for vk in reversed(vk_codes):
            if vk:
                user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.02)

    def _press_key(self, key: str):
        """Press a single key"""
        self._press_hotkey(key)

    def _clipboard_set(self, text: str):
        """Set clipboard content"""
        try:
            process = subprocess.Popen(
                ["clip"], stdin=subprocess.PIPE, shell=True,
            )
            process.communicate(input=text.encode("utf-16le"))
        except Exception:
            # Fallback: tkinter
            try:
                import tkinter as tk
                r = tk.Tk()
                r.withdraw()
                r.clipboard_clear()
                r.clipboard_append(text)
                r.update()
                r.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    bridge = EditorBridge()
    print(f"✅ EditorBridge loaded")
    print(f"   Supported editors: {bridge.supported_editors}")
    print(f"   Modes: clipboard | file_drop | terminal | auto_interact")
    for key, config in EditorBridge.EDITORS.items():
        hotkey = config.get('chat_hotkey', 'N/A')
        print(f"   {config['icon']} {config['display']} ({key}) -- chat: {hotkey}")
