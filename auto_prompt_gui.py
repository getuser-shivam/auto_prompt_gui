#!/usr/bin/env python3
"""
Auto-Prompt Workflow GUI
Chains prompts sequentially and sends them to AI coding editors
for hands-free, automated development.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import os
import sys
import json
import time
import re
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from workflow_engine import WorkflowEngine, Workflow, WorkflowStep
from editor_bridge import EditorBridge
from ai_chatbot import AIChatbot
try:
    from playwright_browser_manager import get_playwright_manager
except ImportError:
    get_playwright_manager = None

# ─────────────────────────────────────────────────────
# Color Palette
# ─────────────────────────────────────────────────────
COLORS = {
    "bg_dark": "#0d1117",
    "bg_mid": "#161b22",
    "bg_card": "#1c2128",
    "bg_input": "#21262d",
    "bg_hover": "#282e36",
    "border": "#30363d",
    "border_light": "#3d444d",
    "text": "#e6edf3",
    "text_dim": "#8b949e",
    "text_muted": "#6e7681",
    "accent": "#58a6ff",
    "accent_hover": "#79c0ff",
    "green": "#3fb950",
    "green_dim": "#1a7f37",
    "red": "#f85149",
    "red_dim": "#a4252a",
    "yellow": "#d29922",
    "purple": "#bc8cff",
    "orange": "#f0883e",
    "cyan": "#39d2c0",
}

STATUS_COLORS = {
    "pending": COLORS["text_muted"],
    "running": COLORS["accent"],
    "completed": COLORS["green"],
    "failed": COLORS["red"],
    "skipped": COLORS["text_dim"],
}

STATUS_ICONS = {
    "pending": "○",
    "running": "⏳",
    "completed": "✅",
    "failed": "❌",
    "skipped": "⏭️",
}


class StepOverlay(tk.Toplevel):
    """Floating, always-on-top status window for workflow execution."""

    def __init__(self, parent, stop_callback):
        super().__init__(parent)
        self.overrideredirect(True)        # Remove window decorations
        self.attributes("-topmost", True)  # Always on top
        self.attributes("-alpha", 0.9)     # Slight transparency
        
        self._x = 0
        self._y = 0
        
        # Initial position (center-ish top)
        screen_w = self.winfo_screenwidth()
        self.geometry(f"340x60+{int(screen_w/2 - 170)}+40")
        
        self.configure(bg=COLORS["bg_card"], bd=1, relief="solid", highlightthickness=1, highlightbackground=COLORS["border"])
        
        # Make draggable
        self.bind("<Button-1>", self._start_move)
        self.bind("<B1-Motion>", self._do_move)
        
        # Layout
        content = tk.Frame(self, bg=COLORS["bg_card"], padx=12, pady=8)
        content.pack(fill=tk.BOTH, expand=True)
        
        self._status_label = tk.Label(
            content, text="Initializing...",
            font=("Segoe UI", 10, "bold"), bg=COLORS["bg_card"], fg=COLORS["accent"]
        )
        self._status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, anchor="w")
        
        # Small Stop Button
        self._stop_btn = tk.Button(
            content, text="⏹ STOP", font=("Segoe UI", 8, "bold"),
            bg=COLORS["red_dim"], fg="#ffffff",
            activebackground=COLORS["red"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=10, pady=4,
            command=stop_callback
        )
        self._stop_btn.pack(side=tk.RIGHT, padx=(10, 0))
        
        # Grip icon for dragging
        tk.Label(content, text="⠿", font=("Segoe UI", 12), bg=COLORS["bg_card"], fg=COLORS["text_muted"]).pack(side=tk.RIGHT, padx=(8, 0))

    def update_status(self, text):
        self._status_label.config(text=text)
        self.lift()

    def _start_move(self, event):
        self._x = event.x
        self._y = event.y

    def _do_move(self, event):
        deltax = event.x - self._x
        deltay = event.y - self._y
        x = self.winfo_x() + deltax
        y = self.winfo_y() + deltay
        self.geometry(f"+{x}+{y}")


class AutoPromptGUI:
    """Modern dark-themed GUI for auto-prompt workflow execution"""

    WORKFLOW_SAVE_DIR = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "workflows"
    )

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("⚡ Auto-Prompt Workflow Runner")
        self.root.geometry("1100x780")
        self.root.minsize(900, 600)
        self.root.configure(bg=COLORS["bg_dark"])

        # Core components
        self.bridge = EditorBridge(editor="antigravity")
        self.engine = WorkflowEngine()
        self.engines = {}
        self.bridges = {}
        self.chatbot = AIChatbot()
        self._overlay: Optional[StepOverlay] = None

        # Bind engine callbacks
                                                
                        
        # Bridge status callback for live AI status
        self.bridge.on_status_change = self._on_bridge_status
        
        # Chatbot callbacks
        self.chatbot.on_response = self._on_chat_response
        self.chatbot.on_error = self._on_chat_error
        self.chatbot.on_status = self._on_chat_status

        # UI state
        self._active_workflow: Optional[Workflow] = None
        self._execution_thread: Optional[threading.Thread] = None
        self._chat_panel_visible = False
        self._connection_monitor_id = None
        self._all_workflows = dict(self.engine.builtin_workflows)
        self.hidden_workflows: List[str] = []
        self._step_frames = []
        self._editor_options = list(self.bridge.supported_editors)
        self._editor_display_by_key = {
            key: EditorBridge.EDITORS.get(key, {}).get("display", key)
            for key in self._editor_options
        }
        self._editor_display_options = [self._editor_display_by_key[key] for key in self._editor_options]
        self._editor_key_by_display = {
            display: key for key, display in self._editor_display_by_key.items()
        }
        self._editor_display_var = tk.StringVar(
            value=self._editor_display_by_key.get("antigravity", "antigravity")
        )
        
        # Mode options for the dropdown
        self.MODES = ["clipboard", "file_drop", "terminal", "auto_interact"]
        self._auto_launch_var = tk.BooleanVar(value=True)
        self._wf_enabled_var = tk.BooleanVar(value=True)
        self._auto_pilot_var = tk.BooleanVar(value=False)
        self._context_agent_var = tk.BooleanVar(value=False)
        self._use_ocr_var = tk.BooleanVar(value=True)
        self._refresh_step_var = tk.BooleanVar(value=True)
        self._auto_rotate_var = tk.BooleanVar(value=True)
        self._auto_republish_var = tk.BooleanVar(value=True)
        self._delay_var = tk.StringVar(value="3.0")
        self._global_delay_var = tk.StringVar(value="")  # Empty = use default delay
        self._loop_var = tk.BooleanVar(value=False)
        self._loop_interval_var = tk.StringVar(value="2")  # 2 mins
        
        # Stop every X steps
        self._stop_every_x_var = tk.StringVar(value="0")  # 0 = disabled
        
        # Overlay visibility
        self._enable_overlay_var = tk.BooleanVar(value=True)
        
        # Chat Provider & Model
        self._chat_provider_var = tk.StringVar(value=self.chatbot.provider)
        self._chat_model_var = tk.StringVar(value=self.chatbot.model)

        # Load saved workflows
        saved = self.engine.load_all_saved(self.WORKFLOW_SAVE_DIR)
        self._all_workflows.update(saved)

        # Build UI
        self._setup_styles()
        self._build_ui()

        # Load settings (including hidden workflows)
        self._load_settings()

        # Populate sidebar (respecting hidden status)
        self._populate_workflow_list()

        # Select first visible workflow
        if self._all_workflows:
            visible_names = [n for n in self._all_workflows.keys() if n not in self.hidden_workflows]
            if visible_names:
                self._select_workflow(visible_names[0])
            else:
                self._select_workflow(list(self._all_workflows.keys())[0])

        # Chat Provider Trace (Add after load to prevent redundant save)
        self._chat_provider_var.trace_add("write", lambda *a: self._on_provider_change())
        self._chat_model_var.trace_add("write", self._on_model_change)
        
        # Proactive save on change (Add after load)
        self._global_delay_var.trace_add("write", lambda *a: self._save_settings())
        self._loop_var.trace_add("write", lambda *a: self._save_settings())
        self._loop_interval_var.trace_add("write", lambda *a: self._save_settings())
        self._stop_every_x_var.trace_add("write", lambda *a: self._save_settings())
        self._enable_overlay_var.trace_add("write", lambda *a: self._save_settings())
        self._use_ocr_var.trace_add("write", lambda *a: self._on_ocr_toggle())
        self._context_agent_var.trace_add("write", lambda *a: self._on_context_agent_toggle())
        self._refresh_step_var.trace_add("write", lambda *a: self._on_refresh_step_toggle())
        self._auto_rotate_var.trace_add("write", lambda *a: self._on_auto_rotate_toggle())
        self._auto_republish_var.trace_add("write", lambda *a: self._on_auto_republish_toggle())
        self._project_var.trace_add("write", lambda *a: self._save_settings())

        # Sync UI and Bridge state
        self._on_editor_change()
        self._on_mode_change()

        # Update initial Project Label text
        self._update_project_ui_labels()

        # Close handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    # ═══════════════════════════════════════════════════
    # STYLES
    # ═══════════════════════════════════════════════════
    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        # Global background
        style.configure(".", background=COLORS["bg_dark"], foreground=COLORS["text"],
                         borderwidth=0, focuscolor=COLORS["accent"])

        # Frames
        style.configure("Dark.TFrame", background=COLORS["bg_dark"])
        style.configure("Card.TFrame", background=COLORS["bg_card"])
        style.configure("Mid.TFrame", background=COLORS["bg_mid"])

        # Labels
        style.configure("Title.TLabel", background=COLORS["bg_dark"],
                         foreground=COLORS["text"], font=("Segoe UI", 18, "bold"))
        style.configure("Subtitle.TLabel", background=COLORS["bg_dark"],
                         foreground=COLORS["text_dim"], font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=COLORS["bg_card"],
                         foreground=COLORS["text"], font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=COLORS["bg_card"],
                         foreground=COLORS["text"], font=("Segoe UI", 11, "bold"))
        style.configure("Mid.TLabel", background=COLORS["bg_mid"],
                         foreground=COLORS["text"], font=("Segoe UI", 10))
        style.configure("Dim.TLabel", background=COLORS["bg_dark"],
                         foreground=COLORS["text_dim"], font=("Segoe UI", 9))
        style.configure("Accent.TLabel", background=COLORS["bg_dark"],
                         foreground=COLORS["accent"], font=("Segoe UI", 10, "bold"))

        # Buttons
        style.configure("Action.TButton", background=COLORS["accent"],
                         foreground="#ffffff", font=("Segoe UI", 10, "bold"),
                         padding=(14, 6))
        style.map("Action.TButton",
                   background=[("active", COLORS["accent_hover"])],
                   foreground=[("active", "#ffffff")])

        style.configure("Danger.TButton", background=COLORS["red_dim"],
                         foreground="#ffffff", font=("Segoe UI", 10, "bold"),
                         padding=(14, 6))
        style.map("Danger.TButton",
                   background=[("active", COLORS["red"])])

        style.configure("Ghost.TButton", background=COLORS["bg_mid"],
                         foreground=COLORS["text_dim"], font=("Segoe UI", 9),
                         padding=(8, 4))
        style.map("Ghost.TButton",
                   background=[("active", COLORS["bg_hover"])],
                   foreground=[("active", COLORS["text"])])

        style.configure("Sidebar.TButton", background=COLORS["bg_mid"],
                         foreground=COLORS["text"], font=("Segoe UI", 10),
                         padding=(10, 8), anchor="w")
        style.map("Sidebar.TButton",
                   background=[("active", COLORS["bg_hover"])])

        style.configure("SidebarActive.TButton", background=COLORS["bg_card"],
                         foreground=COLORS["accent"], font=("Segoe UI", 10, "bold"),
                         padding=(10, 8), anchor="w")

        # Entry
        style.configure("Dark.TEntry", fieldbackground=COLORS["bg_input"],
                         foreground=COLORS["text"], insertcolor=COLORS["text"],
                         borderwidth=1, relief="solid")

        # Combobox
        style.configure("Dark.TCombobox", fieldbackground=COLORS["bg_input"],
                         foreground=COLORS["text"],
                         selectbackground=COLORS["accent"],
                         selectforeground="#ffffff")
        style.map("Dark.TCombobox",
                   fieldbackground=[("readonly", COLORS["bg_input"])],
                   foreground=[("readonly", COLORS["text"])])

        # Progressbar
        style.configure("Accent.Horizontal.TProgressbar",
                         troughcolor=COLORS["bg_input"],
                         background=COLORS["accent"],
                         darkcolor=COLORS["accent"],
                         lightcolor=COLORS["accent_hover"],
                         bordercolor=COLORS["border"],
                         thickness=6)

        # Separator
        style.configure("Dark.TSeparator", background=COLORS["border"])

        # LabelFrame
        style.configure("Card.TLabelframe", background=COLORS["bg_card"],
                         foreground=COLORS["text_dim"],
                         bordercolor=COLORS["border"])
        style.configure("Card.TLabelframe.Label", background=COLORS["bg_card"],
                         foreground=COLORS["text_dim"],
                         font=("Segoe UI", 9, "bold"))

        # Scrollbar styling
        style.configure("Vertical.TScrollbar", gripcount=0,
                         background=COLORS["bg_card"], troughcolor=COLORS["bg_dark"],
                         bordercolor=COLORS["border"], arrowcolor=COLORS["text_dim"],
                         lightcolor=COLORS["bg_card"], darkcolor=COLORS["bg_card"])
        style.map("Vertical.TScrollbar",
                  background=[("active", COLORS["bg_hover"]), ("pressed", COLORS["accent"])])

    # ═══════════════════════════════════════════════════
    # BUILD UI
    # ═══════════════════════════════════════════════════
    def _build_ui(self):
        # ── Top Bar ──
        top_bar = tk.Frame(self.root, bg=COLORS["bg_mid"], height=56)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        top_bar.pack_propagate(False)

        tk.Label(top_bar, text="⚡", font=("Segoe UI", 20),
                 bg=COLORS["bg_mid"], fg=COLORS["yellow"]).pack(side=tk.LEFT, padx=(16, 4))
        tk.Label(top_bar, text="Auto-Prompt Workflow Runner", font=("Segoe UI", 14, "bold"),
                 bg=COLORS["bg_mid"], fg=COLORS["text"]).pack(side=tk.LEFT)
        tk.Label(top_bar, text="Chain prompts → Auto develop", font=("Segoe UI", 9),
                 bg=COLORS["bg_mid"], fg=COLORS["text_dim"]).pack(side=tk.LEFT, padx=(12, 0))

        # Settings button
        settings_btn = tk.Button(
            top_bar, text="⚙ Settings", font=("Segoe UI", 9),
            bg=COLORS["bg_card"], fg=COLORS["text_dim"],
            activebackground=COLORS["bg_hover"], activeforeground=COLORS["text"],
            relief="flat", bd=0, padx=12, pady=4,
            command=self._show_settings,
        )
        settings_btn.pack(side=tk.RIGHT, padx=16)

        # AI Chat toggle button
        self._chat_toggle_btn = tk.Button(
            top_bar, text="🤖 AI Chat", font=("Segoe UI", 9, "bold"),
            bg=COLORS["purple"], fg="#ffffff",
            activebackground=COLORS["accent"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=12, pady=4,
            command=self._toggle_chat_panel,
        )
        self._chat_toggle_btn.pack(side=tk.RIGHT, padx=(0, 6))

        # ── Main horizontal split ──
        main = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
                               bg=COLORS["border"], sashwidth=2, sashrelief="flat")
        main.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # ── LEFT: Workflow Sidebar ──
        sidebar = tk.Frame(main, bg=COLORS["bg_mid"], width=220)
        main.add(sidebar, minsize=180, width=220)

        sidebar_header = tk.Frame(sidebar, bg=COLORS["bg_mid"])
        sidebar_header.pack(fill=tk.X, padx=12, pady=(14, 6))
        tk.Label(sidebar_header, text="WORKFLOWS", font=("Segoe UI", 9, "bold"),
                 bg=COLORS["bg_mid"], fg=COLORS["text_dim"]).pack(side=tk.LEFT)

        add_btn = tk.Button(
            sidebar_header, text="+ New", font=("Segoe UI", 8, "bold"),
            bg=COLORS["green_dim"], fg=COLORS["green"],
            activebackground=COLORS["green"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=8, pady=2,
            command=self._new_workflow,
        )
        add_btn.pack(side=tk.RIGHT)

        self._unhide_btn = tk.Button(
            sidebar_header, text="👁 Show", font=("Segoe UI", 8),
            bg=COLORS["bg_mid"], fg=COLORS["text_dim"],
            activebackground=COLORS["bg_hover"], activeforeground=COLORS["text"],
            relief="flat", bd=0, padx=6, pady=2,
            command=self._show_unhide_dialog,
        )
        # Initially hidden, shown in _populate_workflow_list if needed
        self._unhide_btn.pack_forget()

        # Scrollable workflow list
        sidebar_scroll_frame = tk.Frame(sidebar, bg=COLORS["bg_mid"])
        sidebar_scroll_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._sidebar_canvas = tk.Canvas(
            sidebar_scroll_frame, bg=COLORS["bg_mid"],
            highlightthickness=0, bd=0,
        )
        sidebar_scrollbar = ttk.Scrollbar(sidebar_scroll_frame, orient="vertical",
                                         command=self._sidebar_canvas.yview)
        self._sidebar_list_frame = tk.Frame(self._sidebar_canvas, bg=COLORS["bg_mid"])
        
        self._sidebar_list_frame.bind("<Configure>",
                                lambda e: self._sidebar_canvas.configure(
                                    scrollregion=self._sidebar_canvas.bbox("all")))

        self._sidebar_canvas_window = self._sidebar_canvas.create_window(
            (0, 0), window=self._sidebar_list_frame, anchor="nw"
        )
        self._sidebar_canvas.configure(yscrollcommand=sidebar_scrollbar.set)

        sidebar_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._sidebar_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Make canvas resize inner frame width
        self._sidebar_canvas.bind("<Configure>", 
                                  lambda e: self._sidebar_canvas.itemconfig(self._sidebar_canvas_window, width=e.width))

        # Mouse wheel scrolling
        def _on_sidebar_mousewheel(event):
            self._sidebar_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        self._sidebar_canvas.bind("<Enter>", lambda e: self._sidebar_canvas.bind_all("<MouseWheel>", _on_sidebar_mousewheel))
        self._sidebar_canvas.bind("<Leave>", lambda e: self._sidebar_canvas.unbind_all("<MouseWheel>"))

        # ── RIGHT: Main content area ──
        right = tk.Frame(main, bg=COLORS["bg_dark"])
        main.add(right, minsize=600)

        # ── Right top split: config bar + steps ──
        # Config bar
        config_bar = tk.Frame(right, bg=COLORS["bg_card"], height=50)
        config_bar.pack(fill=tk.X, padx=12, pady=(10, 0))
        config_bar.pack_propagate(False)

        # Container for project path / cloud target controls
        self._target_frame = tk.Frame(config_bar, bg=COLORS["bg_card"])
        self._target_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 4))

        self._project_label = tk.Label(self._target_frame, text="📁 Project:", font=("Segoe UI", 9),
                 bg=COLORS["bg_card"], fg=COLORS["text_dim"])
        self._project_label.pack(side=tk.LEFT, padx=(0, 4))
        
        self._project_var = tk.StringVar(value=str(Path.cwd().parent))
        self._project_entry = tk.Entry(
            self._target_frame, textvariable=self._project_var,
            font=("Segoe UI", 9), bg=COLORS["bg_input"],
            fg=COLORS["text"], insertbackground=COLORS["text"],
            relief="flat", bd=0,
        )
        self._project_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6), ipady=3)

        self._browse_btn = tk.Button(
            self._target_frame, text="Browse", font=("Segoe UI", 8),
            bg=COLORS["bg_input"], fg=COLORS["text_dim"],
            activebackground=COLORS["bg_hover"], activeforeground=COLORS["text"],
            relief="flat", bd=0, padx=8,
            command=self._browse_project,
        )
        self._browse_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._cloud_target_label = tk.Label(
            self._target_frame, 
            text="🌐 Target: Google AI Studio (Web Workspace · No local folder needed)", 
            font=("Segoe UI", 9, "bold"),
            bg=COLORS["bg_card"], fg=COLORS["cyan"]
        )

        self._open_url_btn = tk.Button(
            self._target_frame, text="🌐 Open AI Studio", font=("Segoe UI", 8, "bold"),
            bg=COLORS["bg_input"], fg=COLORS["cyan"],
            activebackground=COLORS["bg_hover"], activeforeground=COLORS["cyan"],
            relief="flat", bd=0, padx=8,
            command=self._open_project_url,
        )

        self._republish_btn = tk.Button(
            self._target_frame, text="🚀 Republish & Test", font=("Segoe UI", 8, "bold"),
            bg=COLORS["green_dim"], fg=COLORS["green"],
            activebackground=COLORS["green"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=8,
            command=self._on_manual_republish,
        )

        # Editor selector
        tk.Label(config_bar, text="Editor:", font=("Segoe UI", 9),
                 bg=COLORS["bg_card"], fg=COLORS["text_dim"]).pack(side=tk.LEFT, padx=(8, 4))
        editor_combo = ttk.Combobox(
            config_bar, textvariable=self._editor_display_var,
            values=self._editor_display_options,
            state="readonly", width=18, style="Dark.TCombobox",
        )
        editor_combo.pack(side=tk.LEFT, padx=(0, 8))
        editor_combo.bind("<<ComboboxSelected>>", self._on_editor_change)

        # Send mode
        tk.Label(config_bar, text="Mode:", font=("Segoe UI", 9),
                 bg=COLORS["bg_card"], fg=COLORS["text_dim"]).pack(side=tk.LEFT, padx=(8, 4))
        self._mode_var = tk.StringVar(value="clipboard")
        mode_combo = ttk.Combobox(
            config_bar, textvariable=self._mode_var,
            values=["clipboard", "file_drop", "terminal", "auto_interact", "ai_chat"],
            state="readonly", width=12, style="Dark.TCombobox",
        )
        mode_combo.pack(side=tk.LEFT, padx=(0, 10))
        mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)

        # Step Delay Override (Global)
        tk.Label(config_bar, text="Step Delay Override (s):", font=("Segoe UI", 9),
                 bg=COLORS["bg_card"], fg=COLORS["text_dim"]).pack(side=tk.LEFT, padx=(8, 4))
        tk.Entry(config_bar, textvariable=self._global_delay_var, width=5,
                 font=("Cascadia Code", 9), bg=COLORS["bg_input"], fg=COLORS["text"],
                 relief="flat", justify="center").pack(side=tk.LEFT, padx=(0, 4))
        
        tk.Button(
            config_bar, text="⚡ Apply", font=("Segoe UI", 8, "bold"),
            bg=COLORS["bg_input"], fg=COLORS["yellow"],
            activebackground=COLORS["bg_hover"], activeforeground=COLORS["yellow"],
            relief="flat", bd=0, padx=8, pady=2,
            command=self._apply_global_delay,
        ).pack(side=tk.LEFT, padx=(0, 8))

        # ── Vertical split: steps editor on top, execution log on bottom ──
        content_pane = tk.PanedWindow(right, orient=tk.VERTICAL,
                                       bg=COLORS["border"], sashwidth=2, sashrelief="flat")
        content_pane.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        # ── STEP EDITOR ──
        steps_outer = tk.Frame(content_pane, bg=COLORS["bg_card"])
        content_pane.add(steps_outer, minsize=200, height=340)

        steps_header = tk.Frame(steps_outer, bg=COLORS["bg_card"])
        steps_header.pack(fill=tk.X, padx=12, pady=(10, 4))

        self._wf_title_label = tk.Label(
            steps_header, text="Select a workflow",
            font=("Segoe UI", 13, "bold"), bg=COLORS["bg_card"], fg=COLORS["text"],
        )
        self._wf_title_label.pack(side=tk.LEFT)

        self._wf_desc_label = tk.Label(
            steps_header, text="",
            font=("Segoe UI", 9), bg=COLORS["bg_card"], fg=COLORS["text_dim"],
        )
        self._wf_desc_label.pack(side=tk.LEFT, padx=(12, 0))

        # Workflow actions row
        wf_actions = tk.Frame(steps_outer, bg=COLORS["bg_card"])
        wf_actions.pack(fill=tk.X, padx=12, pady=(0, 6))

        add_step_btn = tk.Button(
            wf_actions, text="+ Add Step", font=("Segoe UI", 9, "bold"),
            bg=COLORS["green_dim"], fg=COLORS["green"],
            activebackground=COLORS["green"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=10, pady=3,
            command=self._add_step,
        )
        add_step_btn.pack(side=tk.LEFT)

        # Variables button
        vars_btn = tk.Button(
            wf_actions, text="{ } Variables", font=("Segoe UI", 9),
            bg=COLORS["bg_input"], fg=COLORS["text_dim"],
            activebackground=COLORS["bg_hover"], activeforeground=COLORS["text"],
            relief="flat", bd=0, padx=10, pady=3,
            command=self._edit_variables,
        )
        vars_btn.pack(side=tk.LEFT, padx=(8, 0))

        save_wf_btn = tk.Button(
            wf_actions, text="💾 Save", font=("Segoe UI", 9),
            bg=COLORS["bg_input"], fg=COLORS["text_dim"],
            activebackground=COLORS["bg_hover"], activeforeground=COLORS["text"],
            relief="flat", bd=0, padx=10, pady=3,
            command=self._save_current_workflow,
        )
        save_wf_btn.pack(side=tk.LEFT, padx=(8, 0))

        delete_wf_btn = tk.Button(
            wf_actions, text="🗑 Delete Workflow", font=("Segoe UI", 9),
            bg=COLORS["bg_input"], fg=COLORS["red"],
            activebackground=COLORS["red_dim"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=10, pady=3,
            command=self._delete_workflow,
        )
        delete_wf_btn.pack(side=tk.RIGHT)

        # Workflow Enabled checkbox
        self._wf_enabled_var = tk.BooleanVar(value=True)
        enabled_cb = tk.Checkbutton(
            wf_actions, text="Enabled", variable=self._wf_enabled_var,
            bg=COLORS["bg_card"], fg=COLORS["text_dim"],
            selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_card"],
            font=("Segoe UI", 9)
        )
        enabled_cb.pack(side=tk.RIGHT, padx=(4, 0))

        # Step delay (default for new steps) hidden as it's confusing. Use global override or per-step.
        self._delay_var = tk.StringVar(value="5")

        # Scrollable steps list
        steps_canvas_frame = tk.Frame(steps_outer, bg=COLORS["bg_card"])
        steps_canvas_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 8))

        self._steps_canvas = tk.Canvas(
            steps_canvas_frame, bg=COLORS["bg_card"],
            highlightthickness=0, bd=0,
        )
        steps_scrollbar = ttk.Scrollbar(steps_canvas_frame, orient="vertical",
                                         command=self._steps_canvas.yview)
        self._steps_inner = tk.Frame(self._steps_canvas, bg=COLORS["bg_card"])
        self._steps_inner.bind("<Configure>",
                                lambda e: self._steps_canvas.configure(
                                    scrollregion=self._steps_canvas.bbox("all")))

        self._steps_canvas_window = self._steps_canvas.create_window(
            (0, 0), window=self._steps_inner, anchor="nw"
        )
        self._steps_canvas.configure(yscrollcommand=steps_scrollbar.set)

        steps_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._steps_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Make canvas resize inner frame width
        self._steps_canvas.bind("<Configure>", self._on_canvas_resize)

        # Mouse wheel scrolling
        def _on_steps_mousewheel(event):
            self._steps_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        self._steps_canvas.bind("<Enter>", lambda e: self._steps_canvas.bind_all("<MouseWheel>", _on_steps_mousewheel))
        self._steps_canvas.bind("<Leave>", lambda e: self._steps_canvas.unbind_all("<MouseWheel>"))

        # ── EXECUTION LOG ──
        exec_outer = tk.Frame(content_pane, bg=COLORS["bg_mid"])
        content_pane.add(exec_outer, minsize=180)

        exec_header = tk.Frame(exec_outer, bg=COLORS["bg_mid"])
        exec_header.pack(fill=tk.X, padx=12, pady=(10, 4))

        tk.Label(exec_header, text="EXECUTION LOG", font=("Segoe UI", 9, "bold"),
                 bg=COLORS["bg_mid"], fg=COLORS["text_dim"]).pack(side=tk.LEFT)

        # Live AI status indicator
        self._ai_status_var = tk.StringVar(value="")
        self._ai_status_label = tk.Label(
            exec_header, textvariable=self._ai_status_var,
            font=("Segoe UI", 9, "bold"), bg=COLORS["bg_mid"], fg=COLORS["cyan"],
        )
        self._ai_status_label.pack(side=tk.LEFT, padx=(12, 0))

        # Controls
        ctrl_frame = tk.Frame(exec_header, bg=COLORS["bg_mid"])
        ctrl_frame.pack(side=tk.RIGHT)

        self._run_btn = tk.Button(
            ctrl_frame, text="▶  Run", font=("Segoe UI", 10, "bold"),
            bg=COLORS["green_dim"], fg=COLORS["green"],
            activebackground=COLORS["green"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=14, pady=4,
            command=self._run_workflow,
        )
        self._run_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._pause_btn = tk.Button(
            ctrl_frame, text="⏸ Pause", font=("Segoe UI", 10),
            bg=COLORS["bg_card"], fg=COLORS["yellow"],
            activebackground=COLORS["yellow"], activeforeground="#000000",
            relief="flat", bd=0, padx=14, pady=4,
            command=self._pause_resume,
            state="disabled",
        )
        self._pause_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._stop_btn = tk.Button(
            ctrl_frame, text="⏹ Stop", font=("Segoe UI", 10),
            bg=COLORS["bg_card"], fg=COLORS["red"],
            activebackground=COLORS["red"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=14, pady=4,
            command=self._stop_workflow,
            state="disabled",
        )
        self._stop_btn.pack(side=tk.LEFT, padx=(0, 6))

        clear_btn = tk.Button(
            ctrl_frame, text="Clear", font=("Segoe UI", 9),
            bg=COLORS["bg_card"], fg=COLORS["text_dim"],
            activebackground=COLORS["bg_hover"], activeforeground=COLORS["text"],
            relief="flat", bd=0, padx=10, pady=4,
            command=self._clear_log,
        )
        clear_btn.pack(side=tk.LEFT)

        # Loop Controls row
        loop_row = tk.Frame(exec_outer, bg=COLORS["bg_mid"])
        loop_row.pack(fill=tk.X, padx=12, pady=(0, 6))

        tk.Checkbutton(
            loop_row, text="Auto Sync (Loop)", variable=self._loop_var,
            bg=COLORS["bg_mid"], fg=COLORS["text"],
            selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_mid"],
            font=("Segoe UI", 9, "bold")
        ).pack(side=tk.LEFT)

        tk.Checkbutton(
            loop_row, text="Auto OCR Click", variable=self._use_ocr_var,
            bg=COLORS["bg_mid"], fg=COLORS["accent"],
            selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_mid"],
            font=("Segoe UI", 8, "bold")
        ).pack(side=tk.RIGHT, padx=(4, 0))

        self._refresh_step_cb = tk.Checkbutton(
            loop_row, text="🔄 Refresh on Step", variable=self._refresh_step_var,
            bg=COLORS["bg_mid"], fg=COLORS["yellow"],
            selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_mid"],
            font=("Segoe UI", 8, "bold"),
            command=self._on_refresh_step_toggle
        )

        self._auto_rotate_cb = tk.Checkbutton(
            loop_row, text="🔀 Auto-Switch Model", variable=self._auto_rotate_var,
            bg=COLORS["bg_mid"], fg=COLORS["cyan"],
            selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_mid"],
            font=("Segoe UI", 8, "bold"),
            command=self._on_auto_rotate_toggle
        )

        self._auto_republish_cb = tk.Checkbutton(
            loop_row, text="🚀 Auto-Republish & Test", variable=self._auto_republish_var,
            bg=COLORS["bg_mid"], fg=COLORS["green"],
            selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_mid"],
            font=("Segoe UI", 8, "bold"),
            command=self._on_auto_republish_toggle
        )

        tk.Checkbutton(
            loop_row, text="🛸 Context Agent", variable=self._context_agent_var,
            bg=COLORS["bg_mid"], fg=COLORS["cyan"],
            selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_mid"],
            font=("Segoe UI", 9, "bold"),
            command=self._on_context_agent_toggle
        ).pack(side=tk.RIGHT, padx=(12, 0))

        tk.Label(loop_row, text="Interval (min):", font=("Segoe UI", 9),
                 bg=COLORS["bg_mid"], fg=COLORS["text_dim"]).pack(side=tk.LEFT, padx=(12, 4))
        
        tk.Entry(
            loop_row, textvariable=self._loop_interval_var, width=5,
            font=("Segoe UI", 9), bg=COLORS["bg_input"],
            fg=COLORS["text"], insertbackground=COLORS["text"],
            relief="flat", bd=0, justify="center"
        ).pack(side=tk.LEFT, ipady=2)

        # Stop every X steps field
        tk.Label(loop_row, text="Stop every X steps:", font=("Segoe UI", 9),
                 bg=COLORS["bg_mid"], fg=COLORS["text_dim"]).pack(side=tk.LEFT, padx=(20, 4))
        
        tk.Entry(
            loop_row, textvariable=self._stop_every_x_var, width=5,
            font=("Segoe UI", 9), bg=COLORS["bg_input"],
            fg=COLORS["text"], insertbackground=COLORS["text"],
            relief="flat", bd=0, justify="center"
        ).pack(side=tk.LEFT, ipady=2)
        
        tk.Label(loop_row, text="(0=off)", font=("Segoe UI", 8),
                 bg=COLORS["bg_mid"], fg=COLORS["text_muted"]).pack(side=tk.LEFT, padx=(4, 0))

        # Progress bar
        prog_frame = tk.Frame(exec_outer, bg=COLORS["bg_mid"])
        prog_frame.pack(fill=tk.X, padx=12, pady=(0, 4))
        self._progress_var = tk.DoubleVar(value=0)
        self._progress_bar = ttk.Progressbar(
            prog_frame, variable=self._progress_var,
            maximum=100, style="Accent.Horizontal.TProgressbar",
        )
        self._progress_bar.pack(fill=tk.X)

        # Log text with scrollbar
        log_container = tk.Frame(exec_outer, bg=COLORS["bg_dark"])
        log_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self._log_text = tk.Text(
            log_container, wrap=tk.WORD,
            bg=COLORS["bg_dark"], fg=COLORS["text"],
            font=("Cascadia Code", 9), relief="flat", bd=0,
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            padx=12, pady=8,
        )
        log_scrollbar = ttk.Scrollbar(log_container, orient="vertical", command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_scrollbar.set)
        
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Log tags
        self._log_text.tag_configure("timestamp", foreground=COLORS["text_muted"])
        self._log_text.tag_configure("info", foreground=COLORS["accent"])
        self._log_text.tag_configure("success", foreground=COLORS["green"])
        self._log_text.tag_configure("error", foreground=COLORS["red"])
        self._log_text.tag_configure("warning", foreground=COLORS["yellow"])
        self._log_text.tag_configure("step", foreground=COLORS["purple"])
        self._log_text.tag_configure("dim", foreground=COLORS["text_dim"])

        # Status bar
        status_bar = tk.Frame(self.root, bg=COLORS["bg_mid"], height=28)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        status_bar.pack_propagate(False)

        self._status_var = tk.StringVar(value="Ready")
        tk.Label(status_bar, textvariable=self._status_var, font=("Segoe UI", 8),
                 bg=COLORS["bg_mid"], fg=COLORS["text_dim"]).pack(side=tk.LEFT, padx=12)

        self._editor_status = tk.Label(
            status_bar, text="⚡ Antigravity", font=("Segoe UI", 8, "bold"),
            bg=COLORS["bg_mid"], fg=COLORS["accent"],
        )
        self._editor_status.pack(side=tk.RIGHT, padx=12)

        self._chatbot_status_label = tk.Label(
            status_bar, text=self.chatbot.status_text, font=("Segoe UI", 8),
            bg=COLORS["bg_mid"], fg=COLORS["text_dim"],
        )
        self._chatbot_status_label.pack(side=tk.RIGHT, padx=(0, 12))

        # ── AI CHAT PANEL (initially hidden) ──
        self._chat_panel = tk.Frame(self.root, bg=COLORS["bg_card"], width=340)
        # Not packed yet — toggled by _toggle_chat_panel

        # Chat panel header
        chat_header = tk.Frame(self._chat_panel, bg=COLORS["bg_mid"])
        chat_header.pack(fill=tk.X)

        tk.Label(chat_header, text="🤖 AI Assistant", font=("Segoe UI", 11, "bold"),
                 bg=COLORS["bg_mid"], fg=COLORS["text"]).pack(side=tk.LEFT, padx=12, pady=8)

        self._chat_status_var = tk.StringVar(value=self.chatbot.status_text)
        tk.Label(chat_header, textvariable=self._chat_status_var, font=("Segoe UI", 8),
                 bg=COLORS["bg_mid"], fg=COLORS["text_dim"]).pack(side=tk.LEFT, padx=(0, 8), pady=8)

        tk.Button(
            chat_header, text="🗑", font=("Segoe UI", 9),
            bg=COLORS["bg_mid"], fg=COLORS["text_dim"],
            activebackground=COLORS["bg_hover"],
            relief="flat", bd=0, padx=6,
            command=self._clear_chat,
        ).pack(side=tk.RIGHT, padx=8)

        # Quick action buttons
        actions_frame = tk.Frame(self._chat_panel, bg=COLORS["bg_card"])
        actions_frame.pack(fill=tk.X, padx=8, pady=(6, 4))

        tk.Button(
            actions_frame, text="✨ Generate Workflow", font=("Segoe UI", 8, "bold"),
            bg=COLORS["green_dim"], fg=COLORS["green"],
            activebackground=COLORS["green"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=8, pady=3,
            command=self._ai_generate_workflow,
        ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(
            actions_frame, text="🔧 Refine Step", font=("Segoe UI", 8, "bold"),
            bg=COLORS["bg_input"], fg=COLORS["accent"],
            activebackground=COLORS["accent"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=8, pady=3,
            command=self._ai_refine_prompt,
        ).pack(side=tk.LEFT, padx=(4, 4))

        tk.Button(
            actions_frame, text="✨ Suggest", font=("Segoe UI", 8, "bold"),
            bg=COLORS["bg_input"], fg=COLORS["green"],
            activebackground=COLORS["green"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=8, pady=3,
            command=lambda: self._ai_generate_workflow("Suggest the next logical development step based on my project context."),
        ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(
            actions_frame, text="📋 Sync", font=("Segoe UI", 8, "bold"),
            bg=COLORS["bg_input"], fg=COLORS["purple"],
            activebackground=COLORS["purple"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=8, pady=3,
            command=self._on_sync_project,
        ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Checkbutton(
            actions_frame, text="🔄 Auto-Pilot", variable=self._auto_pilot_var,
            font=("Segoe UI", 8), bg=COLORS["bg_card"], fg=COLORS["text_dim"],
            activebackground=COLORS["bg_card"], activeforeground=COLORS["text"],
            selectcolor=COLORS["bg_input"], bd=0
        ).pack(side=tk.LEFT)

        # Chat messages display with scrollbar
        chat_container = tk.Frame(self._chat_panel, bg=COLORS["bg_dark"])
        chat_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 4))

        self._chat_display = tk.Text(
            chat_container, wrap=tk.WORD,
            bg=COLORS["bg_dark"], fg=COLORS["text"],
            font=("Segoe UI", 9), relief="flat", bd=0,
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            padx=10, pady=8, state="disabled",
        )
        chat_scrollbar = ttk.Scrollbar(chat_container, orient="vertical", command=self._chat_display.yview)
        self._chat_display.configure(yscrollcommand=chat_scrollbar.set)
        
        self._chat_display.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        chat_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Chat display tags
        self._chat_display.tag_configure("user", foreground=COLORS["accent"], font=("Segoe UI", 9, "bold"))
        self._chat_display.tag_configure("bot", foreground=COLORS["green"])
        self._chat_display.tag_configure("error", foreground=COLORS["red"])
        self._chat_display.tag_configure("system", foreground=COLORS["text_muted"], font=("Segoe UI", 8, "italic"))

        # Chat input area
        chat_input_frame = tk.Frame(self._chat_panel, bg=COLORS["bg_card"])
        chat_input_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        self._chat_input = tk.Text(
            chat_input_frame, height=3, wrap=tk.WORD,
            bg=COLORS["bg_input"], fg=COLORS["text"],
            font=("Segoe UI", 9), relief="flat", bd=0,
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            padx=8, pady=6,
        )
        self._chat_input.pack(fill=tk.X, pady=(0, 4))
        self._chat_input.bind("<Return>", self._on_chat_enter)
        self._chat_input.insert("1.0", "")

        send_chat_btn = tk.Button(
            chat_input_frame, text="Send  ➤", font=("Segoe UI", 9, "bold"),
            bg=COLORS["accent"], fg="#ffffff",
            activebackground=COLORS["accent_hover"], activeforeground="#ffffff",
            relief="flat", bd=0, padx=14, pady=4,
            command=self._send_chat_message,
        )
        send_chat_btn.pack(side=tk.RIGHT)

        tk.Button(
            chat_input_frame, text="✨ Load Steps", font=("Segoe UI", 8),
            bg=COLORS["bg_input"], fg=COLORS["accent"],
            activebackground=COLORS["bg_hover"],
            relief="flat", bd=0, padx=8,
            command=self._on_manual_load_steps,
        ).pack(side=tk.RIGHT, padx=4)

    # ═══════════════════════════════════════════════════
    # CANVAS HELPERS
    # ═══════════════════════════════════════════════════
    def _on_canvas_resize(self, event):
        self._steps_canvas.itemconfig(self._steps_canvas_window, width=event.width)

    # ═══════════════════════════════════════════════════
    # SIDEBAR
    # ═══════════════════════════════════════════════════
    def _populate_workflow_list(self):
        for child in self._sidebar_list_frame.winfo_children():
            child.destroy()
            
        # Show/hide unhide button
        if self.hidden_workflows:
            self._unhide_btn.pack(side=tk.RIGHT, padx=4)
        else:
            self._unhide_btn.pack_forget()

        for name, wf in self._all_workflows.items():
            if name in self.hidden_workflows:
                continue
            is_active = (self._active_workflow and self._active_workflow.name == name)
            btn_bg = COLORS["bg_card"] if is_active else COLORS["bg_mid"]
            btn_fg = COLORS["accent"] if is_active else COLORS["text"]
            btn_font = ("Segoe UI", 10, "bold") if is_active else ("Segoe UI", 10)

            btn_frame = tk.Frame(self._sidebar_list_frame, bg=btn_bg, cursor="hand2")
            btn_frame.pack(fill=tk.X, pady=2, ipady=6)

            # Left accent bar for active
            if is_active:
                accent_bar = tk.Frame(btn_frame, bg=COLORS["accent"], width=3)
                accent_bar.pack(side=tk.LEFT, fill=tk.Y)

            icon = "▶" if is_active else "○"
            label = tk.Label(
                btn_frame, text=f"  {icon}  {name}",
                font=btn_font, bg=btn_bg, fg=btn_fg,
                anchor="w",
            )
            label.pack(fill=tk.X, padx=4)

            desc = tk.Label(
                btn_frame, text=f"     {len(wf.steps)} steps",
                font=("Segoe UI", 8), bg=btn_bg, fg=COLORS["text_muted"],
                anchor="w",
            )
            desc.pack(fill=tk.X, padx=4)

            # Click handler
            for widget in (btn_frame, label, desc):
                widget.bind("<Button-1>", lambda e, n=name: self._select_workflow(n))

    def _select_workflow(self, name: str):
        if name in self._all_workflows:
            self._active_workflow = self._all_workflows[name]
            self._wf_title_label.config(text=self._active_workflow.name)
            self._wf_desc_label.config(text=self._active_workflow.description)
            self._render_steps()
            self._populate_workflow_list()

    def _show_unhide_dialog(self):
        if not self.hidden_workflows:
            return
            
        dialog = tk.Toplevel(self.root)
        dialog.title("Hidden Workflows")
        dialog.geometry("340x450")
        dialog.configure(bg=COLORS["bg_card"])
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text="Hidden Workflows", font=("Segoe UI", 11, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text"]).pack(pady=15)
                 
        list_container = tk.Frame(dialog, bg=COLORS["bg_card"])
        list_container.pack(fill=tk.BOTH, expand=True, padx=20)
        
        def unhide(name):
            if name in self.hidden_workflows:
                self.hidden_workflows.remove(name)
                self._populate_workflow_list()
                self._save_settings()
                if not self.hidden_workflows:
                    dialog.destroy()
                else:
                    refresh()

        def refresh():
            for child in list_container.winfo_children(): child.destroy()
            for name in self.hidden_workflows:
                f = tk.Frame(list_container, bg=COLORS["bg_mid"])
                f.pack(fill=tk.X, pady=2)
                tk.Label(f, text=name, bg=COLORS["bg_mid"], fg=COLORS["text"], font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=10, pady=8)
                tk.Button(f, text="Unhide", font=("Segoe UI", 8, "bold"), bg=COLORS["accent"], fg="#ffffff",
                          relief="flat", bd=0, padx=10, pady=4,
                          command=lambda n=name: unhide(n)).pack(side=tk.RIGHT, padx=5)
        
        refresh()
        
        tk.Button(dialog, text="Close", font=("Segoe UI", 10), bg=COLORS["bg_input"], fg=COLORS["text"],
                  relief="flat", padx=20, pady=6, command=dialog.destroy).pack(pady=20)

    # ═══════════════════════════════════════════════════
    # STEP EDITOR
    # ═══════════════════════════════════════════════════
    def _render_steps(self):
        """Render all steps of the active workflow in the editor"""
        for child in self._steps_inner.winfo_children():
            child.destroy()
        self._step_frames.clear()

        if not self._active_workflow:
            return

        for i, step in enumerate(self._active_workflow.steps):
            self._create_step_card(i, step)

    def _create_step_card(self, index: int, step: WorkflowStep):
        """Create a single step card widget"""
        status_color = STATUS_COLORS.get(step.status, COLORS["text_muted"])
        status_icon = STATUS_ICONS.get(step.status, "○")

        card = tk.Frame(self._steps_inner, bg=COLORS["bg_input"], bd=0,
                         highlightbackground=COLORS["border"], highlightthickness=1)
        card.pack(fill=tk.X, padx=6, pady=3, ipady=4)

        # Header row
        header = tk.Frame(card, bg=COLORS["bg_input"])
        header.pack(fill=tk.X, padx=8, pady=(6, 2))

        # Status dot
        tk.Label(header, text=status_icon, font=("Segoe UI", 10),
                 bg=COLORS["bg_input"], fg=status_color).pack(side=tk.LEFT, padx=(0, 6))

        # Step name — editable
        name_var = tk.StringVar(value=step.name)
        name_entry = tk.Entry(
            header, textvariable=name_var,
            font=("Segoe UI", 10, "bold"), bg=COLORS["bg_input"],
            fg=COLORS["text"], insertbackground=COLORS["text"],
            relief="flat", bd=0,
        )
        name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        name_var.trace_add("write", lambda *a, i=index, v=name_var: self._update_step_name(i, v.get()))

        # Step success/failure badges
        if getattr(step, "success_count", 0) > 0 or getattr(step, "failure_count", 0) > 0:
            badge_text = f"✅{step.success_count}"
            if step.failure_count > 0:
                badge_text += f" ❌{step.failure_count}"
            tk.Label(
                header, text=badge_text,
                font=("Segoe UI", 8, "bold"),
                bg=COLORS["bg_dark"],
                fg=COLORS["green"] if step.failure_count == 0 else COLORS["yellow"],
                padx=6, pady=1
            ).pack(side=tk.LEFT, padx=(6, 4))

        enabled_var = tk.BooleanVar(value=step.enabled)
        enabled_cb = tk.Checkbutton(
            header, text="Enabled", variable=enabled_var,
            bg=COLORS["bg_input"], fg=COLORS["text_dim"],
            selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_input"],
            font=("Segoe UI", 8),
            command=lambda i=index, v=enabled_var: self._toggle_step(i, v.get()),
        )
        enabled_cb.pack(side=tk.RIGHT, padx=(4, 0))

        # Individual Step Delay
        tk.Label(header, text="Delay(s):", font=("Segoe UI", 8),
                 bg=COLORS["bg_input"], fg=COLORS["text_dim"]).pack(side=tk.RIGHT, padx=(4, 0))
        delay_var = tk.StringVar(value=str(step.delay_after))
        delay_entry = tk.Entry(
            header, textvariable=delay_var, width=4,
            font=("Segoe UI", 8), bg=COLORS["bg_input"],
            fg=COLORS["text"], insertbackground=COLORS["text"],
            relief="flat", bd=0, justify="center"
        )
        delay_entry.pack(side=tk.RIGHT, padx=(0, 2))
        delay_var.trace_add("write", lambda *a, i=index, v=delay_var: self._update_step_delay(i, v.get()))

        # Move / delete buttons
        btn_frame = tk.Frame(header, bg=COLORS["bg_input"])
        btn_frame.pack(side=tk.RIGHT, padx=(8, 0))

        if index > 0:
            tk.Button(
                btn_frame, text="↑", font=("Segoe UI", 9),
                bg=COLORS["bg_input"], fg=COLORS["text_dim"],
                activebackground=COLORS["bg_hover"],
                relief="flat", bd=0, padx=4,
                command=lambda i=index: self._move_step(i, i - 1),
            ).pack(side=tk.LEFT)

        if index < len(self._active_workflow.steps) - 1:
            tk.Button(
                btn_frame, text="↓", font=("Segoe UI", 9),
                bg=COLORS["bg_input"], fg=COLORS["text_dim"],
                activebackground=COLORS["bg_hover"],
                relief="flat", bd=0, padx=4,
                command=lambda i=index: self._move_step(i, i + 1),
            ).pack(side=tk.LEFT)

        tk.Button(
            btn_frame, text="✕", font=("Segoe UI", 9),
            bg=COLORS["bg_input"], fg=COLORS["red"],
            activebackground=COLORS["red_dim"],
            relief="flat", bd=0, padx=4,
            command=lambda i=index: self._remove_step(i),
        ).pack(side=tk.LEFT, padx=(4, 0))

        # AI Refine Button
        tk.Button(
            btn_frame, text="✨ AI", font=("Segoe UI", 8, "bold"),
            bg=COLORS["bg_input"], fg=COLORS["cyan"],
            activebackground=COLORS["bg_hover"], activeforeground=COLORS["cyan"],
            relief="flat", bd=0, padx=6,
            command=lambda i=index: self._ai_refine_prompt(i),
        ).pack(side=tk.LEFT, padx=(6, 0))

        # Prompt text area
        prompt_text = tk.Text(
            card, height=3, wrap=tk.WORD,
            bg=COLORS["bg_dark"], fg=COLORS["text"],
            font=("Cascadia Code", 9), relief="flat", bd=0,
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            padx=8, pady=4,
        )
        prompt_text.pack(fill=tk.X, padx=8, pady=(2, 8))
        prompt_text.insert("1.0", step.prompt)
        prompt_text.bind("<KeyRelease>",
                          lambda e, i=index, t=prompt_text: self._update_step_prompt(i, t))

        self._step_frames.append(card)

    def _update_step_name(self, index: int, name: str):
        if self._active_workflow and 0 <= index < len(self._active_workflow.steps):
            self._active_workflow.steps[index].name = name

    def _update_step_prompt(self, index: int, text_widget: tk.Text):
        if self._active_workflow and 0 <= index < len(self._active_workflow.steps):
            self._active_workflow.steps[index].prompt = text_widget.get("1.0", "end-1c")

    def _update_step_delay(self, index: int, value: str):
        if self._active_workflow and 0 <= index < len(self._active_workflow.steps):
            try:
                self._active_workflow.steps[index].delay_after = float(value)
            except ValueError:
                pass  # Ignore invalid input while typing

    def _toggle_step(self, index: int, enabled: bool):
        if self._active_workflow and 0 <= index < len(self._active_workflow.steps):
            self._active_workflow.steps[index].enabled = enabled

    def _move_step(self, from_idx: int, to_idx: int):
        if self._active_workflow:
            self._active_workflow.move_step(from_idx, to_idx)
            self._render_steps()

    def _remove_step(self, index: int):
        if self._active_workflow:
            step_name = self._active_workflow.steps[index].name
            if messagebox.askyesno("Remove Step", f"Remove '{step_name}'?"):
                self._active_workflow.remove_step(index)
                self._render_steps()

    def _add_step(self):
        if not self._active_workflow:
            messagebox.showinfo("Info", "Please select or create a workflow first.")
            return

        num = len(self._active_workflow.steps) + 1
        try:
            delay = float(self._delay_var.get())
        except ValueError:
            delay = 5.0

        new_step = WorkflowStep(
            name=f"Step {num}",
            prompt="Enter your prompt here...",
            delay_after=delay,
        )
        self._active_workflow.add_step(new_step)
        self._render_steps()

        # Scroll to bottom
        self.root.after(100, lambda: self._steps_canvas.yview_moveto(1.0))

    # ═══════════════════════════════════════════════════
    # WORKFLOW CRUD
    # ═══════════════════════════════════════════════════
    def _new_workflow(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("New Workflow")
        dialog.geometry("400x200")
        dialog.configure(bg=COLORS["bg_card"])
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Workflow Name:", font=("Segoe UI", 10),
                 bg=COLORS["bg_card"], fg=COLORS["text"]).pack(padx=20, pady=(20, 4), anchor="w")
        name_var = tk.StringVar()
        name_entry = tk.Entry(dialog, textvariable=name_var, font=("Segoe UI", 11),
                               bg=COLORS["bg_input"], fg=COLORS["text"],
                               insertbackground=COLORS["text"], relief="flat")
        name_entry.pack(fill=tk.X, padx=20, ipady=4)
        name_entry.focus()

        tk.Label(dialog, text="Description:", font=("Segoe UI", 10),
                 bg=COLORS["bg_card"], fg=COLORS["text"]).pack(padx=20, pady=(12, 4), anchor="w")
        desc_var = tk.StringVar()
        desc_entry = tk.Entry(dialog, textvariable=desc_var, font=("Segoe UI", 10),
                               bg=COLORS["bg_input"], fg=COLORS["text"],
                               insertbackground=COLORS["text"], relief="flat")
        desc_entry.pack(fill=tk.X, padx=20, ipady=4)

        def create():
            name = name_var.get().strip()
            if not name:
                return
            wf = Workflow(name=name, description=desc_var.get().strip())
            self._all_workflows[name] = wf
            self._select_workflow(name)
            dialog.destroy()

        tk.Button(dialog, text="Create", font=("Segoe UI", 10, "bold"),
                   bg=COLORS["accent"], fg="#ffffff",
                   activebackground=COLORS["accent_hover"],
                   relief="flat", bd=0, padx=20, pady=6,
                   command=create).pack(pady=16)

        dialog.bind("<Return>", lambda e: create())

    def _apply_global_delay(self):
        """Bulk apply the global override to all individual steps of the active workflow"""
        if not self._active_workflow:
            return
        
        global_delay_str = self._global_delay_var.get().strip()
        if not global_delay_str:
            messagebox.showinfo("Info", "Enter a delay value first.")
            return

        try:
            g_delay = float(global_delay_str)
            for step in self._active_workflow.steps:
                step.delay_after = g_delay
            self._log(f"⚡ Applied global delay {g_delay}s to all steps in '{self._active_workflow.name}'.", "info")
            self._render_steps()
        except ValueError:
            messagebox.showerror("Error", "Invalid delay value.")

    def _save_current_workflow(self):
        if not self._active_workflow:
            return

        try:
            path = self.engine.save_workflow(self._active_workflow, self.WORKFLOW_SAVE_DIR)
            self._active_workflow.filepath = path
            self._log(f"Workflow saved to {path}", "success")
        except Exception as e:
            self._log(f"Failed to save workflow: {e}", "error")

    def _delete_workflow(self):
        if not self._active_workflow:
            return
        
        wf = self._active_workflow
        name = wf.name
        
        if not messagebox.askyesno("Delete Workflow", f"Delete '{name}'?"):
            return

        # Check if it's a builtin
        if name in self.engine.builtin_workflows:
            # If it's a builtin, we can't delete it from the app logic, 
            # but we can try to delete any user-saved version of it.
            fpath = wf.filepath
            if fpath and os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                    self._log(f"Saved version of built-in workflow deleted: {fpath}", "info")
                except Exception:
                    pass
            
            if messagebox.askyesno("Hide Workflow", 
                                 f"'{name}' is a built-in workflow and cannot be deleted permanently.\n\nWould you like to hide it from the sidebar instead?"):
                self.hidden_workflows.append(name)
                self._active_workflow = None
                self._populate_workflow_list()
                self._save_settings()
            
            self._render_steps()
            return

        del self._all_workflows[name]
        self._active_workflow = None

        # Remove saved file
        fpath = wf.filepath
        if not fpath:
            # Fallback to generated name if not explicitly set
            safe_name = name.lower().replace(" ", "_").replace("/", "_")
            fpath = os.path.join(self.WORKFLOW_SAVE_DIR, f"workflow_{safe_name}.json")
            
        if fpath and os.path.isfile(fpath):
            try:
                os.remove(fpath)
                self._log(f"Workflow file deleted: {fpath}", "success")
            except Exception as e:
                self._log(f"Failed to delete file: {e}", "error")

        if self._all_workflows:
            first_name = list(self._all_workflows.keys())[0]
            self._select_workflow(first_name)
        else:
            self._wf_title_label.config(text="No workflows")
            self._wf_desc_label.config(text="")
            self._render_steps()

        self._populate_workflow_list()

    # ═══════════════════════════════════════════════════
    # VARIABLES EDITOR
    # ═══════════════════════════════════════════════════
    def _edit_variables(self):
        if not self._active_workflow:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Workflow Variables")
        dialog.geometry("500x400")
        dialog.configure(bg=COLORS["bg_card"])
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Template Variables", font=("Segoe UI", 12, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text"]).pack(padx=20, pady=(16, 4), anchor="w")
        tk.Label(dialog, text="Use {variable_name} in your prompts. Set values below:",
                 font=("Segoe UI", 9), bg=COLORS["bg_card"], fg=COLORS["text_dim"]
                 ).pack(padx=20, pady=(0, 12), anchor="w")

        # Common variables
        common_vars = [
            ("project_path", self._project_var.get()),
            ("feature_name", ""),
            ("file_path", ""),
            ("bug_description", ""),
        ]

        entries = {}
        for var_name, default in common_vars:
            current = self._active_workflow.variables.get(var_name, default)
            row = tk.Frame(dialog, bg=COLORS["bg_card"])
            row.pack(fill=tk.X, padx=20, pady=3)
            tk.Label(row, text=f"{{{var_name}}}:", font=("Cascadia Code", 9),
                     bg=COLORS["bg_card"], fg=COLORS["cyan"], width=18, anchor="w"
                     ).pack(side=tk.LEFT)
            var = tk.StringVar(value=current)
            tk.Entry(row, textvariable=var, font=("Segoe UI", 9),
                     bg=COLORS["bg_input"], fg=COLORS["text"],
                     insertbackground=COLORS["text"], relief="flat"
                     ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)
            entries[var_name] = var

        def save():
            for var_name, var in entries.items():
                val = var.get().strip()
                if val:
                    self._active_workflow.variables[var_name] = val
            dialog.destroy()
            self._log("Variables updated", "info")

        tk.Button(dialog, text="Save Variables", font=("Segoe UI", 10, "bold"),
                   bg=COLORS["accent"], fg="#ffffff",
                   activebackground=COLORS["accent_hover"],
                   relief="flat", bd=0, padx=20, pady=6,
                   command=save).pack(pady=20)

    # ═══════════════════════════════════════════════════
    # EXECUTION
    # ═══════════════════════════════════════════════════

    def _get_engine(self, wf_name=None):
        if wf_name is None:
            if not self._active_workflow: return self.engine
            wf_name = self._active_workflow.name
        if wf_name not in self.engines:
            e = __import__("workflow_engine").WorkflowEngine()
            e.on_step_start = lambda i, s, w=wf_name: self._on_step_start(i, s, w)
            e.on_step_complete = lambda i, s, r, w=wf_name: self._on_step_complete(i, s, r, w)
            e.on_error = lambda i, s, err, w=wf_name: self._on_step_error(i, s, err, w)
            e.on_progress = lambda i, tot, pct, w=wf_name: self._on_progress(i, tot, pct, w)
            e.on_workflow_done = lambda wf, status, w=wf_name: self._on_workflow_done(wf, status, w)
            e.on_loop_wait = lambda remaining, w=wf_name: self._on_loop_wait(remaining, w)
            e.on_step_retry = lambda i, s, rc, rl, res, w=wf_name: self._on_step_retry(i, s, rc, rl, res, w)
            e.on_step_failure_recovery = lambda i, s, res, w=wf_name: self._on_step_failure_recovery(i, s, res, w)
            
            b = self._get_bridge(wf_name)
            e.send_prompt_fn = b.send_prompt
            self.engines[wf_name] = e
        return self.engines[wf_name]

    def _get_bridge(self, wf_name=None):
        if wf_name is None:
            if not self._active_workflow: return self.bridge
            wf_name = self._active_workflow.name
        if wf_name not in self.bridges:
            b = __import__("editor_bridge").EditorBridge(self._editor_var.get())
            self.bridges[wf_name] = b
        return self.bridges[wf_name]

    def _run_workflow(self):
        if not self._active_workflow:
            messagebox.showinfo("Info", "No workflow selected.")
            return

        if self._get_engine().is_running:
            messagebox.showinfo("Info", "A workflow is already running.")
            return

        # Create Overlay (if enabled)
        if self._overlay is not None:
            self._overlay.destroy()
            self._overlay = None
            
        if self._enable_overlay_var.get():
            self._overlay = StepOverlay(self.root, self._stop_workflow)

        # Update bridge settings
        editor_key = self._get_selected_editor_key()
        self._get_bridge().editor = editor_key
        self._get_bridge().mode = self._mode_var.get()

        if editor_key == "google_ai_studio":
            # Google AI Studio is cloud/browser-based; NO local project folder needed or checked!
            self._get_bridge().project_path = Path.cwd()
            self._get_bridge().use_autopilot_context = False  # NEVER scan disk for web studio!
            self._active_workflow.variables.setdefault("project_path", "this workspace")
        else:
            proj_str = self._project_var.get().strip()
            try:
                self._get_bridge().project_path = Path(proj_str) if proj_str else Path.cwd()
            except Exception:
                self._get_bridge().project_path = Path.cwd()
            if proj_str:
                self._active_workflow.variables.setdefault("project_path", proj_str)

        self._log(f"▶ Starting workflow: {self._active_workflow.name}", "info")
        self._log(f"  Editor: {self._get_bridge().editor_display_name}  |  Mode: {self._get_bridge().mode}", "dim")

        # Wire up the correct send function based on mode
        if self._get_bridge().mode == "auto_interact":
            if self._get_bridge().editor == "clipboard":
                # Special Case: Clipboard target + Auto-Interaction = Internal AI
                if not self.chatbot.is_ready:
                    messagebox.showerror("Error", "No-Cost AI Chatbot not ready.")
                    return
                
                self._get_engine().send_and_wait_fn = self.chatbot.send_message_blocking
                self._get_engine().send_prompt_fn = None
                self._log("  🤖 Smart Routing: sending prompt directly to Internal AI (Pollinations)", "info")
                if not self._chat_panel_visible:
                    self._toggle_chat_panel()
            else:
                # Standard Case: External Editor + Auto-Interaction
                if editor_key == "google_ai_studio" and get_playwright_manager:
                    try:
                        pw = get_playwright_manager()
                        if not pw.is_connected():
                            pw.connect_cdp()
                        if pw.is_connected():
                            self._log("  🟢 Playwright DOM Engine Active: Direct DOM injection & 0ms completion tracking", "success")
                    except Exception as e:
                        logger.debug(f"Playwright CDP check: {e}")

                self._get_engine().send_and_wait_fn = self._send_external_with_logging
                self._get_engine().send_prompt_fn = None
                self._log(f"  🤖 Smart Routing: will type into {self._get_bridge().editor_display_name} + wait for completion", "info")
        else:
            self._get_engine().send_and_wait_fn = None
            

        # Update button states
        self._run_btn.config(state="disabled")
        self._pause_btn.config(state="normal")
        self._stop_btn.config(state="normal")
        self._status_var.set("Running...")
        global_delay = None
        if self._global_delay_var.get().strip():
            try:
                global_delay = float(self._global_delay_var.get().strip())
            except ValueError:
                pass

        if self._get_bridge().mode == "auto_interact" and global_delay is not None and global_delay > 10.0:
            self._log(f"⚡ Smart Auto-Interact: AI completion is dynamically detected via OCR/UIA. Bypassing {global_delay}s blind delay to start next step without delay.", "info")
            global_delay = 0.0
            self._global_delay_var.set("0")
            self._save_settings()

        for step in self._active_workflow.steps:
            step.status = "pending"
        
        # Set global delay override in engine instead of mutating steps
        self._get_engine().global_delay_override = global_delay
        
        self._render_steps()

        # Update loop and stop settings
        self._get_engine().loop_mode = self._loop_var.get()
        self._get_engine()._steps_since_last_stop = 0
        try:
            mins = float(self._loop_interval_var.get())
            self._get_engine().loop_interval = max(0.1, mins * 60.0)
        except ValueError:
            self._get_engine().loop_interval = 120.0

        try:
            stop_val = int(self._stop_every_x_var.get().strip())
            self._get_engine().stop_every_x = max(0, stop_val)
        except ValueError:
            self._get_engine().stop_every_x = 0

        # Start!
        self._get_engine().start(self._active_workflow)

    def _pause_resume(self):
        if self._get_engine().is_paused:
            self._get_engine().resume()
            self._pause_btn.config(text="⏸ Pause")
            self._status_var.set("Running...")
            self._log("▶ Resumed", "info")
        else:
            self._get_engine().pause()
            self._pause_btn.config(text="▶ Resume")
            self._status_var.set("Paused")
            self._log("⏸ Paused", "warning")

    def _stop_workflow(self):
        self._get_engine().cancel()
        self.bridge.cancel_wait()  # also cancel any active wait-for-completion
        self._loop_var.set(False)  # stop loop on manual stop
        self._log("⏹ Cancelling...", "warning")
        
        if self._overlay is not None:
            self._overlay.destroy()
            self._overlay = None

    # ═══════════════════════════════════════════════════
    # ENGINE CALLBACKS (called from background thread)
    # ═══════════════════════════════════════════════════
    def _send_external_with_logging(self, prompt: str, context: str = "") -> str:
        """Helper to send prompt to external editor AND log it in internal chatbot history"""
        # Log to chatbot so the UI panel stays in sync as a 'summary' of conversation
        display_prompt = prompt
        if context:
            display_prompt = f"[Context: {context}]\n\n{prompt}"
        
        self.chatbot.add_history("user", prompt) # Keep it simple in history
        self._append_chat(f"↗ Sending to {self.bridge.editor_display_name}: {prompt}\n", "system")
        
        # Do the actual interaction
        result = self.bridge.send_and_wait(prompt)
        
        # Log the completion too
        self.chatbot.add_history("assistant", f"[Prompt executed in {self.bridge.editor_display_name}]")
        return result

    def _on_workflow_done(self, workflow, status, wf_name=None):
        if wf_name and (not self._active_workflow or self._active_workflow.name != wf_name): return
        """Called when a workflow run completes"""
        self.root.after(0, self._render_steps)
        self.root.after(0, self._update_ui_state)
        
        if status == "completed":
            self.root.after(0, lambda: self._append_chat(f"🏁 Workflow '{workflow.name}' completed successfully!\n\n", "system"))
            # Auto-Republish & Test for Google AI Studio
            if self._get_selected_editor_key() == "google_ai_studio" and self._auto_republish_var.get():
                self.root.after(1000, self._on_manual_republish)
            # Continuous Auto-Pilot Logic
            if self._auto_pilot_var.get():
                self.root.after(1500, self._on_autopilot_next)
        elif status == "cancelled":
            self.root.after(0, lambda: self._append_chat(f"⏹️ Workflow '{workflow.name}' was cancelled.\n\n", "system"))
        elif status.startswith("error"):
            self.root.after(0, lambda: self._append_chat(f"❌ Workflow '{workflow.name}' failed: {status}\n\n", "error"))

    def _on_autopilot_next(self):
        """Auto-Pilot: Suggest and execute next step"""
        self._append_chat("🔄 Auto-Pilot: Thinking about the next step...\n", "system")
        # Ask AI for next step
        self._ai_generate_workflow("Suggest the next logical development step based on my project context. RETURN STEPS ONLY.")

    def _on_step_start(self, index, step, wf_name=None):
        if wf_name and (not self._active_workflow or self._active_workflow.name != wf_name): return
        self.root.after(0, self._ui_step_start, index, step.name)

    def _ui_step_start(self, index: int, name: str):
        self._log(f"⏳ Step {index + 1}: {name}", "step")
        if self._overlay is not None:
            steps_count = len(self._active_workflow.steps)
            self._overlay.update_status(f"Step {index + 1}/{steps_count}: {name}")
        self._render_steps()

    def _on_editor_change(self, event=None):
        editor_key = self._get_selected_editor_key()
        self.bridge.editor = editor_key
        display_name = self.bridge.editor_display_name
        
        # Update Status Bar
        icon = EditorBridge.EDITORS.get(editor_key, {}).get("icon", "⚡")
        self._editor_status.config(text=f"{icon} {display_name}")
        self._status_var.set(f"Editor: {display_name} | Mode: {self.bridge.mode}")
        self._log(f"Editor switched to {display_name}", "info")
        
        # Update Project UI Labels and Mode
        self._update_project_ui_labels()
        
        # If AI Studio is selected, default mode should be auto_interact (or terminal/browser)
        if editor_key == "google_ai_studio":
            if self._mode_var.get() == "file_drop":
                self._mode_var.set("auto_interact")
                self._on_mode_change()
        self._save_settings()

    def _on_refresh_step_toggle(self):
        enabled = self._refresh_step_var.get()
        self.bridge.refresh_before_step = enabled
        self._log(f"Auto-refresh on step: {'enabled' if enabled else 'disabled'}", "info")
        self._save_settings()

    def _on_auto_rotate_toggle(self):
        enabled = self._auto_rotate_var.get()
        self.bridge.auto_rotate_model = enabled
        self._log(f"Auto-rotate model on quota: {'enabled' if enabled else 'disabled'}", "info")
        self._save_settings()

    def _on_auto_republish_toggle(self):
        enabled = self._auto_republish_var.get()
        self.bridge.auto_republish_test = enabled
        self._log(f"Auto-republish & test on finish: {'enabled' if enabled else 'disabled'}", "info")
        self._save_settings()

    def _on_manual_republish(self):
        """Trigger project publication and live browser preview test"""
        def _task():
            self._log("Initiating project Republish & Test in Google AI Studio...", "info")
            self._status_var.set("Republishing project...")
            success = self.bridge.republish_and_test_ai_studio()
            if success:
                self._log("✅ Republish and browser test completed successfully!", "success")
                self._status_var.set("Live app opened in browser")
            else:
                self._log("⚠️ Republish / Visit did not complete automatically.", "warning")
                self._status_var.set("Ready")
        threading.Thread(target=_task, daemon=True).start()

    def _update_project_ui_labels(self):
        """Update the Project Path / Cloud Target controls based on editor type"""
        editor_key = self._get_selected_editor_key()
        
        if editor_key == "google_ai_studio":
            # For Google AI Studio: Cloud-based web editor, NO local folder input needed or checked
            if hasattr(self, "_project_label"):
                self._project_label.pack_forget()
            if hasattr(self, "_project_entry"):
                self._project_entry.pack_forget()
            if hasattr(self, "_browse_btn"):
                self._browse_btn.pack_forget()
            
            if hasattr(self, "_cloud_target_label"):
                self._cloud_target_label.pack(side=tk.LEFT, padx=(0, 8))
            if hasattr(self, "_open_url_btn"):
                self._open_url_btn.config(text="🌐 Open AI Studio", fg=COLORS["cyan"])
                self._open_url_btn.pack(side=tk.LEFT, padx=(0, 6))
            if hasattr(self, "_republish_btn"):
                self._republish_btn.pack(side=tk.LEFT, padx=(0, 6))
            
            # Show Refresh on Step, Auto-Rotate, Auto-Republish checkboxes for Google AI Studio
            if hasattr(self, "_refresh_step_cb"):
                self._refresh_step_cb.pack(side=tk.RIGHT, padx=(6, 0))
            if hasattr(self, "_auto_rotate_cb"):
                self._auto_rotate_cb.pack(side=tk.RIGHT, padx=(6, 0))
            if hasattr(self, "_auto_republish_cb"):
                self._auto_republish_cb.pack(side=tk.RIGHT, padx=(6, 0))

            # Start dynamic browser process monitoring
            self._start_connection_monitor()
        else:
            self._stop_connection_monitor()
            if hasattr(self, "_cloud_target_label"):
                self._cloud_target_label.pack_forget()
            if hasattr(self, "_open_url_btn"):
                self._open_url_btn.pack_forget()
            if hasattr(self, "_republish_btn"):
                self._republish_btn.pack_forget()
            if hasattr(self, "_refresh_step_cb"):
                self._refresh_step_cb.pack_forget()
            if hasattr(self, "_auto_rotate_cb"):
                self._auto_rotate_cb.pack_forget()
            if hasattr(self, "_auto_republish_cb"):
                self._auto_republish_cb.pack_forget()
            
            # Re-pack local folder controls inside target frame
            if hasattr(self, "_project_label"):
                self._project_label.config(text="📁 Project:")
                self._project_label.pack(side=tk.LEFT, padx=(0, 4))
            if hasattr(self, "_project_entry"):
                self._project_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6), ipady=3)
            if hasattr(self, "_browse_btn"):
                self._browse_btn.pack(side=tk.LEFT, padx=(0, 4))

    def _start_connection_monitor(self):
        """Start polling the bridge's connection state."""
        self._stop_connection_monitor()
        self._check_connection_loop()

    def _stop_connection_monitor(self):
        """Stop polling the bridge's connection state."""
        if hasattr(self, "_connection_monitor_id") and self._connection_monitor_id:
            self.root.after_cancel(self._connection_monitor_id)
            self._connection_monitor_id = None

    def _check_connection_loop(self):
        """Check if target browser is connected, using a background thread to avoid freezing the GUI."""
        def _bg_check():
            try:
                connected = self.bridge.is_connected
            except Exception:
                connected = False
            # Update UI on the main thread
            self.root.after(0, lambda: self._update_connection_status(connected))
        
        thread = threading.Thread(target=_bg_check, daemon=True)
        thread.start()
        
        # Schedule next check
        self._connection_monitor_id = self.root.after(3000, self._check_connection_loop)

    def _update_connection_status(self, is_connected: bool):
        """Update the connection button text/color on the main thread."""
        if self._get_selected_editor_key() == "google_ai_studio":
            if get_playwright_manager:
                try:
                    pw = get_playwright_manager()
                    if pw.is_connected():
                        self._open_url_btn.config(text="🟢 Playwright DOM (Active)", fg=COLORS["green"])
                        return
                except Exception:
                    pass

            if is_connected:
                url = getattr(self.bridge, "detected_browser_url", "")
                if url and "aistudio" in url:
                    self._open_url_btn.config(text="🔗 AI Studio (OS Window)", fg=COLORS["yellow"])
                else:
                    self._open_url_btn.config(text="🔗 Connected", fg=COLORS["green"])
            else:
                self._open_url_btn.config(text="🚀 Launch AI Studio (Automated)", fg=COLORS["cyan"])

    def _open_project_url(self):
        """Open or connect to Google AI Studio with Playwright CDP automation"""
        url = getattr(self.bridge, "detected_browser_url", "")
        if not url or not url.startswith("http"):
            url = "https://aistudio.google.com/"

        if get_playwright_manager:
            pw = get_playwright_manager()
            self._log(f"Launching/Connecting to automated Google AI Studio browser ({url})...", "info")
            def _bg_launch():
                connected = pw.launch_ai_studio_browser(url)
                if connected:
                    self._log("🟢 Playwright DOM automation connected successfully! (Direct DOM control active)", "success")
                    self.root.after(0, lambda: self._update_connection_status(True))
                else:
                    self._log("⚠️ Could not attach Playwright CDP, opening default browser...", "warning")
                    import webbrowser
                    webbrowser.open(url)
            threading.Thread(target=_bg_launch, daemon=True).start()
        else:
            self._log(f"Opening Google AI Studio: {url}", "success")
            import webbrowser
            webbrowser.open(url)

    def _on_mode_change(self, event=None):
        mode = self._mode_var.get()
        self.bridge.mode = mode
        self._log(f"Send mode: {mode}", "info")

        if mode == "auto_interact":
            cur_delay = self._global_delay_var.get().strip()
            try:
                if float(cur_delay) > 10.0:
                    self._global_delay_var.set("0")
                    self._log("⚡ Switched to Auto-Interact: Step Delay Override reset to 0s (AI completion is dynamically detected via OCR/UIA, no blind delay needed).", "info")
                    self._save_settings()
            except ValueError:
                pass
        
        # If project path is a URL and we are in auto_interact mode with AI Studio, we can detect it
        project_path = self._project_var.get().strip()
        editor_display = self._editor_display_var.get()
        editor = self._editor_key_by_display.get(editor_display)
        
        if (editor == "google_ai_studio" and 
            (project_path.startswith("http://") or project_path.startswith("https://"))):
            self._log(f"Detected Project URL for AI Studio: {project_path}", "success")

    def _on_step_complete(self, index, step, result, wf_name=None):
        if wf_name and (not self._active_workflow or self._active_workflow.name != wf_name): return
        self.root.after(0, self._ui_step_complete, index, step.name, result)

    def _ui_step_complete(self, index: int, name: str, result: str):
        self._log(f"✅ Step {index + 1} complete: {name}", "success")
        if result:
            # Show first 200 chars of result
            preview = result[:200].replace("\n", " ")
            self._log(f"   → {preview}", "dim")
        self._render_steps()

    def _on_step_error(self, index, step, error, wf_name=None):
        if wf_name and (not self._active_workflow or self._active_workflow.name != wf_name): return
        self.root.after(0, self._ui_step_error, index, step.name, error)

    def _ui_step_error(self, index: int, name: str, error: str):
        self._log(f"❌ Step {index + 1} failed: {name} — {error}", "error")
        self._render_steps()

    def _on_step_retry(self, index, step, attempt, max_retries, error, wf_name=None):
        if wf_name and (not self._active_workflow or self._active_workflow.name != wf_name): return
        self.root.after(0, self._ui_step_retry, index, step.name, attempt, max_retries, error)

    def _ui_step_retry(self, index: int, name: str, attempt: int, max_retries: int, error: str):
        preview = error[:80].replace("\n", " ") if error else "Execution error"
        self._log(f"⚠️ Step {index + 1} ({name}) failed: {preview}", "warning")
        self._log(f"   🔄 Auto-Rerunning Step {index + 1} (Attempt {attempt}/{max_retries}) before proceeding...", "warning")
        self._status_var.set(f"Rerunning Step {index + 1} ({attempt}/{max_retries})...")
        if self._overlay is not None:
            self._overlay.update_status(f"Step {index + 1} Retry {attempt}/{max_retries}: {name}")
        self._render_steps()

    def _on_step_failure_recovery(self, index, step, error, wf_name=None):
        if wf_name and (not self._active_workflow or self._active_workflow.name != wf_name): return
        """Recovery hook called before retrying a failed step"""
        if self._get_selected_editor_key() == "google_ai_studio":
            err_lower = error.lower()
            if any(k in err_lower for k in ["quota", "exhausted", "rate limit", "overloaded", "resource has been exhausted", "try again later"]):
                self._log("🔀 Quota exhaustion detected during recovery! Auto-switching to next free model...", "warning")
                try:
                    self.bridge.rotate_google_ai_studio_model()
                except Exception as e:
                    print(f"Recovery rotate error: {e}")
            elif any(k in err_lower for k in ["unexpected error", "reload", "finish what you", "disconnected", "timed out"]):
                self._log("🔄 Session error detected: Reloading Google AI Studio tab for clean retry...", "info")
                try:
                    self.bridge.refresh_google_ai_studio()
                except Exception as e:
                    print(f"Recovery refresh error: {e}")

    def _update_ui_state(self):
        """Helper to reset UI elements after workflow completion/cancellation."""
        self._run_btn.config(state="normal")
        self._pause_btn.config(state="disabled", text="⏸ Pause")
        self._stop_btn.config(state="disabled")
        self._progress_var.set(0)
        self._status_var.set("Ready")
        self._ai_status_var.set("")
        
        if self._overlay is not None:
            self._overlay.destroy()
            self._overlay = None

    def _on_progress(self, current, total, percent, wf_name=None):
        if wf_name and (not self._active_workflow or self._active_workflow.name != wf_name): return
        self.root.after(0, self._progress_var.set, percent)

    def _on_bridge_status(self, status: str, detail: str):
        """Called from bridge (background thread) when AI status changes"""
        self.root.after(0, self._ui_bridge_status, status, detail)

    def _ui_bridge_status(self, status: str, detail: str):
        """Update the live AI status indicator"""
        status_colors = {
            "typing": COLORS["yellow"],
            "waiting": COLORS["cyan"],
            "cooldown": COLORS["green"],
            "done": COLORS["green"],
        }
        color = status_colors.get(status, COLORS["text_dim"])
        self._ai_status_label.config(fg=color)
        self._ai_status_var.set(detail)
        self._status_var.set(detail)

    def _on_loop_wait(self, countdown, wf_name=None):
        if wf_name and (not self._active_workflow or self._active_workflow.name != wf_name): return
        self.root.after(0, self._ui_loop_wait, countdown)

    def _ui_loop_wait(self, countdown: float):
        detail = f"🔄 Next run in: {int(countdown)}s"
        self._ai_status_label.config(fg=COLORS["yellow"])
        self._ai_status_var.set(detail)
        self._status_var.set(detail)

    # ═══════════════════════════════════════════════════
    # LOG
    # ═══════════════════════════════════════════════════
    def _log(self, message: str, tag: str = ""):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_text.insert("end", f"[{timestamp}] ", "timestamp")
        self._log_text.insert("end", f"{message}\n", tag if tag else "")
        self._log_text.see("end")

    def _clear_log(self):
        self._log_text.delete("1.0", "end")

    # ═══════════════════════════════════════════════════
    # SETTINGS
    # ═══════════════════════════════════════════════════
    def _show_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings")
        dialog.geometry("460x420")
        dialog.configure(bg=COLORS["bg_card"])
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="⚙ Settings", font=("Segoe UI", 14, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text"]).pack(padx=20, pady=(16, 12), anchor="w")

        # ── AI Chatbot Settings ──
        api_frame = tk.LabelFrame(
            dialog, text="🤖 AI Assistant Settings",
            bg=COLORS["bg_card"], fg=COLORS["text_dim"],
            font=("Segoe UI", 9, "bold"), bd=1,
            relief="groove", padx=12, pady=8,
        )
        api_frame.pack(fill=tk.X, padx=20, pady=(0, 8))

        # Provider Selection
        tk.Label(api_frame, text="AI Provider:", font=("Segoe UI", 9),
                 bg=COLORS["bg_card"], fg=COLORS["text"]).pack(anchor="w")
        
        provider_combo = ttk.Combobox(
            api_frame, textvariable=self._chat_provider_var,
            values=self.chatbot.PROVIDERS,
            state="readonly", font=("Segoe UI", 9)
        )
        provider_combo.pack(fill=tk.X, pady=(2, 6))

        # Model Selection
        tk.Label(api_frame, text="Model:", font=("Segoe UI", 9),
                 bg=COLORS["bg_card"], fg=COLORS["text"]).pack(anchor="w")
        
        model_combo = ttk.Combobox(
            api_frame, textvariable=self._chat_model_var,
            state="readonly", font=("Segoe UI", 9)
        )
        model_combo.pack(fill=tk.X, pady=(2, 8))

        def update_models(*args):
            provider = self._chat_provider_var.get()
            models = self.chatbot.MODELS.get(provider, [])
            model_combo["values"] = models
            if self._chat_model_var.get() not in models:
                self._chat_model_var.set(models[0] if models else "")
        
        self._chat_provider_var.trace_add("write", update_models)
        update_models() # Initial population

        tk.Label(api_frame, text="API Key (Required for Groq):", font=("Segoe UI", 9),
                 bg=COLORS["bg_card"], fg=COLORS["text"]).pack(anchor="w")

        api_key_var = tk.StringVar(value=self.chatbot._api_key or "")
        api_entry = tk.Entry(
            api_frame, textvariable=api_key_var, show="•",
            font=("Cascadia Code", 10), bg=COLORS["bg_input"],
            fg=COLORS["text"], insertbackground=COLORS["text"],
            relief="flat", bd=0,
        )
        api_entry.pack(fill=tk.X, pady=(4, 4), ipady=3)

        api_btn_frame = tk.Frame(api_frame, bg=COLORS["bg_card"])
        api_btn_frame.pack(fill=tk.X, pady=(4, 0))

        api_status_label = tk.Label(
            api_btn_frame, text=self.chatbot.status_text, font=("Segoe UI", 8),
            bg=COLORS["bg_card"], fg=COLORS["text_dim"],
        )
        api_status_label.pack(side=tk.LEFT)

        def save_api_key():
            key = api_key_var.get().strip()
            self.chatbot.set_api_key(key)
            self.chatbot.set_model(self._chat_model_var.get())
            # Connectivity check for Groq
            if "Groq" in self._chat_provider_var.get():
                if not key:
                    messagebox.showwarning("Groq", "Please enter an API key for Groq.")
                    return
                # Simple connectivity check
                self._append_chat("🔍 Testing Groq connection...\n", "system")
                def check_done(reply):
                    self.root.after(0, lambda: self._append_chat("✅ Groq connected successfully!\n", "system"))
                self.chatbot.send_message("Testing connection. Reply with 'OK'.", callback=check_done)
            
            status = self.chatbot.status_text
            api_status_label.config(text=status)
            if hasattr(self, "_chat_status_var"): self._chat_status_var.set(status)
            if hasattr(self, "_chatbot_status_label"): self._chatbot_status_label.config(text=status)
            self._save_settings()

        tk.Button(
            api_btn_frame, text="Save & Connect", font=("Segoe UI", 8, "bold"),
            bg=COLORS["green_dim"], fg=COLORS["green"],
            activebackground=COLORS["green"],
            relief="flat", bd=0, padx=12, pady=3,
            command=save_api_key,
        ).pack(side=tk.RIGHT)

        # Import workflow from file
        import_frame = tk.Frame(dialog, bg=COLORS["bg_card"])
        import_frame.pack(fill=tk.X, padx=20, pady=4)
        tk.Label(import_frame, text="Import Workflow:", font=("Segoe UI", 10),
                 bg=COLORS["bg_card"], fg=COLORS["text"]).pack(side=tk.LEFT)
        tk.Button(import_frame, text="Import JSON", font=("Segoe UI", 9),
                   bg=COLORS["bg_input"], fg=COLORS["text_dim"],
                   activebackground=COLORS["bg_hover"],
                   relief="flat", bd=0, padx=10, pady=3,
                   command=lambda: self._import_workflow(dialog)
                   ).pack(side=tk.RIGHT)

        # Export workflow
        export_frame = tk.Frame(dialog, bg=COLORS["bg_card"])
        export_frame.pack(fill=tk.X, padx=20, pady=4)
        tk.Label(export_frame, text="Export Current:", font=("Segoe UI", 10),
                 bg=COLORS["bg_card"], fg=COLORS["text"]).pack(side=tk.LEFT)
        tk.Button(export_frame, text="Export JSON", font=("Segoe UI", 9),
                   bg=COLORS["bg_input"], fg=COLORS["text_dim"],
                   activebackground=COLORS["bg_hover"],
                   relief="flat", bd=0, padx=10, pady=3,
                   command=lambda: self._export_workflow(dialog)
                   ).pack(side=tk.RIGHT)

        # Auto-focus toggle
        focus_frame = tk.Frame(dialog, bg=COLORS["bg_card"])
        focus_frame.pack(fill=tk.X, padx=20, pady=12)
        auto_focus_var = tk.BooleanVar(value=self.bridge._auto_focus)
        tk.Checkbutton(
            focus_frame, text="Auto-focus editor window after sending prompt",
            variable=auto_focus_var, bg=COLORS["bg_card"], fg=COLORS["text"],
            selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_card"],
            font=("Segoe UI", 10),
            command=lambda: [setattr(self.bridge, "_auto_focus", auto_focus_var.get()), self._save_settings()],
        ).pack(anchor="w")

        # Workflow save directory
        dir_frame = tk.Frame(dialog, bg=COLORS["bg_card"])
        dir_frame.pack(fill=tk.X, padx=20, pady=4)
        tk.Label(dir_frame, text="Save directory:", font=("Segoe UI", 9),
                 bg=COLORS["bg_card"], fg=COLORS["text_dim"]).pack(anchor="w")
        tk.Label(dir_frame, text=self.WORKFLOW_SAVE_DIR, font=("Cascadia Code", 8),
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"]).pack(anchor="w")
        
        # Enable Overlay
        overlay_frame = tk.Frame(dialog, bg=COLORS["bg_card"])
        overlay_frame.pack(fill=tk.X, padx=20, pady=8)
        tk.Checkbutton(
            overlay_frame, text="Show Floating Step Overlay",
            variable=self._enable_overlay_var, bg=COLORS["bg_card"], fg=COLORS["accent"],
            selectcolor=COLORS["bg_dark"], activebackground=COLORS["bg_card"],
            font=("Segoe UI", 10, "bold")
        ).pack(anchor="w")

        tk.Button(dialog, text="Close", font=("Segoe UI", 10),
                   bg=COLORS["bg_input"], fg=COLORS["text"],
                   activebackground=COLORS["bg_hover"],
                   relief="flat", bd=0, padx=20, pady=6,
                   command=dialog.destroy).pack(pady=16)

    def _import_workflow(self, parent):
        path = filedialog.askopenfilename(
            parent=parent, filetypes=[("JSON files", "*.json")],
            title="Import Workflow",
        )
        if path:
            try:
                wf = self.engine.load_workflow(path)
                self._all_workflows[wf.name] = wf
                self._select_workflow(wf.name)
                self._log(f"Imported workflow: {wf.name}", "success")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import: {e}")

    def _export_workflow(self, parent):
        if not self._active_workflow:
            return
        path = filedialog.asksaveasfilename(
            parent=parent,
            filetypes=[("JSON files", "*.json")],
            defaultextension=".json",
            initialfile=f"workflow_{self._active_workflow.name.lower().replace(' ', '_')}.json",
            title="Export Workflow",
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self._active_workflow.to_dict(), f, indent=2, ensure_ascii=False)
                self._log(f"Exported workflow to {path}", "success")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export: {e}")

    # ═══════════════════════════════════════════════════
    # MISC
    # ═══════════════════════════════════════════════════
    def _browse_project(self):
        path = filedialog.askdirectory(initialdir=self._project_var.get())
        if path:
            self._project_var.set(path)
            self.bridge.project_path = Path(path)
            self._save_settings()

    def _get_selected_editor_key(self) -> str:
        display = self._editor_display_var.get()
        if display in self._editor_key_by_display:
            return self._editor_key_by_display[display]
        if display in EditorBridge.EDITORS:
            return display
        for k, v in EditorBridge.EDITORS.items():
            if v.get("display", "").lower() in display.lower() or k.lower() in display.lower():
                return k
        return "antigravity"

    def _on_provider_change(self):
        self.chatbot.set_provider(self._chat_provider_var.get())
        # Model might have been reset by set_provider default
        self._chat_model_var.set(self.chatbot.model)
        
        status = self.chatbot.status_text
        if hasattr(self, "_chat_status_var"):
            self._chat_status_var.set(status)
        if hasattr(self, "_chatbot_status_label"):
            self._chatbot_status_label.config(text=status)
        self._log(f"AI Provider switched to {self._chat_provider_var.get()}", "info")
        self._save_settings()

    def _on_model_change(self, *args):
        self.chatbot.set_model(self._chat_model_var.get())
        self._log(f"AI Model switched to {self._chat_model_var.get()}", "info")
        self._save_settings()

    def _on_mode_change(self, event=None):
        self.bridge.mode = self._mode_var.get()
        self._log(f"Send mode: {self._mode_var.get()}", "info")
        self._save_settings()

    def _on_context_agent_toggle(self, event=None):
        self.bridge.use_autopilot_context = self._context_agent_var.get()
        state = "enabled 🚀" if self.bridge.use_autopilot_context else "disabled 🛑"
        self._log(f"Context Agent {state}", "info")
        self._save_settings()

    def _on_ocr_toggle(self, event=None):
        self.bridge.use_ocr_click = self._use_ocr_var.get()
        self._save_settings()

    def _load_project_path(self):
        """Try to load project path and API keys from .env (Legacy/Fallback)"""
        for env_name in [".env", ".env.example"]:
            env_file = Path(os.path.dirname(os.path.abspath(__file__))) / env_name
            if env_file.exists():
                try:
                    with open(env_file) as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("PROJECT_PATH="):
                                path = line.split("=", 1)[1].strip()
                                if path and not self._project_var.get():
                                    self._project_var.set(path)
                            elif line.startswith("POLLINATIONS_API_KEY="):
                                key = line.split("=", 1)[1].strip()
                                if key and not key.startswith("your_") and not self.chatbot._api_key:
                                    self.chatbot.set_api_key(key)
                                    self._chat_status_var.set(self.chatbot.status_text)
                                    self._chatbot_status_label.config(text=self.chatbot.status_text)
                except Exception:
                    pass

    def _get_settings_path(self) -> Path:
        return Path(os.path.dirname(os.path.abspath(__file__))) / "gui_settings.json"

    def _save_settings(self):
        """Save GUI presets to JSON file"""
        try:
            settings = {
                "project_path": self._project_var.get(),
                "editor": self._get_selected_editor_key(),
                "mode": self._mode_var.get(),
                "global_delay": self._global_delay_var.get(),
                "loop": self._loop_var.get(),
                "loop_interval": self._loop_interval_var.get(),
                "stop_every_x": self._stop_every_x_var.get(),
                "auto_focus": self.bridge._auto_focus,
                "api_key": self.chatbot._api_key or "",
                "provider": self._chat_provider_var.get(),
                "model": self._chat_model_var.get(),
                "enable_overlay": self._enable_overlay_var.get(),
                "use_ocr_click": self._use_ocr_var.get(),
                "context_agent": self._context_agent_var.get(),
                "refresh_before_step": self._refresh_step_var.get(),
                "auto_rotate_model": self._auto_rotate_var.get(),
                "auto_republish_test": self._auto_republish_var.get(),
                "hidden_workflows": self.hidden_workflows,
            }
            with open(self._get_settings_path(), "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def _load_settings(self):
        """Load GUI presets from JSON file"""
        # 1. Try JSON settings first (Preferred)
        spath = self._get_settings_path()
        if spath.exists():
            try:
                with open(spath, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                
                if "project_path" in settings:
                    self._project_var.set(settings["project_path"])
                if "editor" in settings:
                    raw_editor = settings["editor"]
                    matched_key = "antigravity"
                    if raw_editor in self._editor_display_by_key:
                        matched_key = raw_editor
                    elif raw_editor in self._editor_key_by_display:
                        matched_key = self._editor_key_by_display[raw_editor]
                    else:
                        for k, v in EditorBridge.EDITORS.items():
                            if k.lower() in raw_editor.lower() or v.get("display", "").lower() in raw_editor.lower():
                                matched_key = k
                                break
                    display = self._editor_display_by_key.get(matched_key, "Google Antigravity")
                    self._editor_display_var.set(display)
                if "mode" in settings:
                    self._mode_var.set(settings["mode"])
                if "global_delay" in settings:
                    self._global_delay_var.set(settings["global_delay"])
                if "loop" in settings:
                    self._loop_var.set(settings["loop"])
                if "loop_interval" in settings:
                    self._loop_interval_var.set(settings["loop_interval"])
                if "stop_every_x" in settings:
                    self._stop_every_x_var.set(settings["stop_every_x"])
                if "auto_focus" in settings:
                    self.bridge._auto_focus = settings["auto_focus"]
                if "enable_overlay" in settings:
                    self._enable_overlay_var.set(settings["enable_overlay"])
                if "use_ocr_click" in settings:
                    self._use_ocr_var.set(settings["use_ocr_click"])
                if "refresh_before_step" in settings:
                    self._refresh_step_var.set(settings["refresh_before_step"])
                    self.bridge.refresh_before_step = settings["refresh_before_step"]
                if "auto_rotate_model" in settings:
                    self._auto_rotate_var.set(settings["auto_rotate_model"])
                    self.bridge.auto_rotate_model = settings["auto_rotate_model"]
                if "auto_republish_test" in settings:
                    self._auto_republish_var.set(settings["auto_republish_test"])
                    self.bridge.auto_republish_test = settings["auto_republish_test"]
                if "context_agent" in settings:
                    self._context_agent_var.set(settings["context_agent"])
                    # Use a small delay or call directly if bridge is ready
                    self._on_context_agent_toggle()
                if "provider" in settings:
                    self._chat_provider_var.set(settings["provider"])
                    self.chatbot.set_provider(settings["provider"])
                if "model" in settings:
                    self._chat_model_var.set(settings["model"])
                    self.chatbot.set_model(settings["model"])
                if "api_key" in settings and settings["api_key"]:
                    self.chatbot.set_api_key(settings["api_key"])
                if "hidden_workflows" in settings:
                    self.hidden_workflows = settings["hidden_workflows"]
                
                status = self.chatbot.status_text
                if hasattr(self, "_chat_status_var"): self._chat_status_var.set(status)
                if hasattr(self, "_chatbot_status_label"): self._chatbot_status_label.config(text=status)
            except Exception as e:
                print(f"Error loading settings: {e}")

        # 2. Fallback to .env for legacy support
        self._load_project_path()

    def _on_closing(self):
        """Save settings before closing"""
        self._stop_connection_monitor()
        self._save_settings()
        self.root.destroy()

    # ═══════════════════════════════════════════════════
    # AI CHATBOT
    # ═══════════════════════════════════════════════════
    def _toggle_chat_panel(self):
        """Show/hide the AI chat panel"""
        if self._chat_panel_visible:
            self._chat_panel.pack_forget()
            self._chat_panel_visible = False
            self._chat_toggle_btn.config(bg=COLORS["purple"])
        else:
            self._chat_panel.pack(side=tk.RIGHT, fill=tk.Y, before=self.root.winfo_children()[1])
            self._chat_panel_visible = True
            self._chat_toggle_btn.config(bg=COLORS["green"])
            if not self.chatbot.is_ready:
                self._append_chat("Welcome! No-Cost AI (Pollinations) is ready to help.\n", "system")
                self._append_chat("No keys or signup required.\n\n", "system")

    def _send_chat_message(self):
        """Send the current input to the chatbot"""
        message = self._chat_input.get("1.0", "end-1c").strip()
        if not message:
            return

        self._chat_input.delete("1.0", tk.END)
        self._append_chat(f"You: {message}\n", "user")

        # Build workflow context
        context = ""
        if self._active_workflow:
            steps_info = [f"  {i+1}. {s.name}: {s.prompt[:80]}..."
                          for i, s in enumerate(self._active_workflow.steps)]
            context = f"Workflow: {self._active_workflow.name}\nSteps:\n" + "\n".join(steps_info)

        self.chatbot.send_message(message, context=context)

    def _on_chat_enter(self, event):
        """Handle Enter key in chat input (Shift+Enter for newline)"""
        if not event.state & 0x1:  # Shift not held
            self._send_chat_message()
            return "break"  # Prevent newline

    def _on_chat_response(self, response: str):
        """Called from background thread when chatbot responds"""
        self.root.after(0, self._append_chat, f"🤖 {response}\n\n", "bot")
        
        steps = self._extract_steps_from_text(response)
        if steps:
            self.root.after(100, lambda s=json.dumps(steps): self._show_apply_steps_button(s))

    def _extract_steps_from_text(self, text: str) -> List[str]:
        """Try multiple ways to extract workflow steps from a block of text"""
        if not text: return []
        
        # Pre-clean smart quotes
        t = text.replace("“", "\"").replace("”", "\"").replace("‘", "'").replace("’", "'")
        
        # 1. Try to find the largest bracketed block
        s = t.find("[")
        e = t.rfind("]")
        if s != -1 and e > s:
            blob = t[s:e+1]
            try:
                # Clean markdown
                if "```" in blob:
                    matches = re.findall(r"```(?:json)?([\s\S]*?)```", blob)
                    if matches: blob = matches[0].strip()
                
                # Standard JSON
                try: return json.loads(blob)
                except:
                    # Trailing comma
                    try: return json.loads(re.sub(r",\s*\]", "]", blob))
                    except: pass
                    
                # Single quotes to double quotes (Dangerous but sometimes needed)
                try:
                    # Simple heuristic: replace ' with " if not preceded by \
                    fixed = re.sub(r"(?<!\\)'", '"', blob)
                    return json.loads(fixed)
                except: pass
            except:
                pass
        
        # 2. Heuristic: Look for items that look like steps inside the bracketed area
        if s != -1 and e > s:
            inner = t[s+1:e]
            # Match anything between quotes
            items = re.findall(r"['\"]([\s\S]*?)['\"]", inner)
            if len(items) >= 2:
                # Filter out very short strings that might be keys/garbage
                steps = [i.strip() for i in items if len(i.strip()) > 10]
                if steps: return steps

        # 3. Regex for numbered items in the whole text (handles "1. ...", '"1. ..."', etc.)
        lines = t.split("\n")
        steps = []
        for line in lines:
            line = line.strip().strip(",").strip()
            if not line: continue
            # Look for "1. ", "Step 1: ", etc. (Optionally wrapped in quotes)
            match = re.search(r"^\"?(\d+[\.\)]|Step\s*\d+:)\s*(.*)", line, re.I)
            if match:
                content = match.group(2).strip().strip("\"").strip()
                steps.append(f"{match.group(1)} {content}")
        
        if len(steps) >= 2: return steps

        # 4. Final Fail-safe: Just find any balanced quoted blocks > 30 chars
        quotes = re.findall(r"['\"]([^'\"]{30,})['\"]", t)
        if quotes: return quotes
        
        # 5. SUPER DUMB FALLBACK: Anything that looks like "1. Something"
        # finds sequences like: 1. Text, "1. Text", 2) Text, etc.
        dumb_steps = re.findall(r"(?:\n|^)\s*\"?(\d+[\.\)]\s*[^\"\n\],}]+)", t)
        if len(dumb_steps) >= 2:
            return [s.strip().strip("\"").strip() for s in dumb_steps]
            
        return []

    def _on_chat_error(self, error: str):
        """Called from background thread on chatbot error"""
        self.root.after(0, self._append_chat, f"❌ {error}\n\n", "error")

    def _on_chat_status(self, status: str):
        """Called from background thread for status updates"""
        self.root.after(0, self._chat_status_var.set, status)

    def _apply_steps_from_chat(self, json_data: str, auto_start: bool = False):
        """Parse and apply steps from JSON detected in chat"""
        try:
            steps = json.loads(json_data)
            if not isinstance(steps, list):
                # If it's a dict, try to find a list inside
                if isinstance(steps, dict):
                    found_list = None
                    for v in steps.values():
                        if isinstance(v, list):
                            found_list = v
                            break
                    if found_list: steps = found_list
                    else: raise ValueError("JSON must be a list of steps")
                else:
                    raise ValueError("JSON must be a list of steps")

            # Create or update workflow
            wf = self._active_workflow
            if not wf or not (not wf.steps or messagebox.askyesno("Load Steps", f"Add {len(steps)} steps to current workflow?")):
                # Create a new one
                name = f"AI_{datetime.now().strftime('%H%M%S')}"
                wf = Workflow(name=name, description="Steps from chat")
                self._all_workflows[name] = wf
                self._active_workflow = wf
                self._populate_workflow_list()
            
            for s in steps:
                prompt_val = ""
                name_val = "Step"
                if isinstance(s, str):
                    cleaned_step = s.strip()
                    if ":" in cleaned_step:
                        parts = cleaned_step.split(":", 1)
                        name_val = parts[0].strip()[:30]
                        if "." in name_val: name_val = name_val.split(".", 1)[1].strip()
                        prompt_val = parts[1].strip()
                    else:
                        prompt_val = cleaned_step
                elif isinstance(s, dict):
                    prompt_val = s.get("prompt", s.get("text", ""))
                    name_val = s.get("name", s.get("title", f"Step {len(wf.steps)+1}"))
                
                if prompt_val:
                    wf.add_step(WorkflowStep(name=name_val, prompt=prompt_val))
            
            self._render_steps()
            self._append_chat(f"✅ Loaded {len(steps)} steps into '{wf.name}'.\n\n", "system")
            
            if auto_start:
                # Give a moment for the UI to update
                self.root.after(1000, self._run_workflow)

        except Exception as e:
            self._append_chat(f"❌ Failed to apply steps: {e}\n\n", "error")

    def _show_apply_steps_button(self, json_data: str):
        """Show a button in the chat display to apply the detected steps"""
        self._chat_display.config(state="normal")
        # Auto-pilot awareness
        auto_start = self._auto_pilot_var.get()
        btn = tk.Button(
            self._chat_display, text="📋 Load these steps" + (" & Run" if auto_start else ""), 
            font=("Segoe UI", 9, "bold"),
            bg=COLORS["green"] if auto_start else COLORS["accent"], fg="#ffffff",
            activebackground=COLORS["green_dim"] if auto_start else COLORS["accent_hover"], 
            activeforeground="#ffffff",
            relief="flat", bd=0, padx=10, pady=4,
            command=lambda: self._apply_steps_from_chat(json_data, auto_start=auto_start)
        )
        self._chat_display.window_create(tk.END, window=btn)
        self._chat_display.insert(tk.END, "\n\n")
        self._chat_display.see(tk.END)
        self._chat_display.config(state="disabled")

        if auto_start:
            # In auto-pilot mode, we also click it automatically after a small delay!
            # Or just call the function directly.
            self.root.after(2000, lambda: self._apply_steps_from_chat(json_data, auto_start=True))

    def _on_manual_load_steps(self):
        """Scan entire chat history for steps and try to apply them"""
        # Read directly from the widget for maximum reliability
        all_text = self._chat_display.get("1.0", tk.END)
        steps = self._extract_steps_from_text(all_text)
        
        if steps:
            self._apply_steps_from_chat(json.dumps(steps), auto_start=False)
        else:
            # Debug info: tell user what we found
            snippet = all_text.strip()[:100].replace("\n", " ") + "..."
            messagebox.showinfo("Scan Results", 
                f"I couldn't find any clear workflow steps in the chat display.\n\n"
                "Tip: Try asking the AI 'list out the steps one by one clearly'.")

    def _append_chat(self, text: str, tag: str = ""):
        """Append text to the chat display"""
        self._chat_display.config(state="normal")
        if tag:
            self._chat_display.insert(tk.END, text, tag)
        else:
            self._chat_display.insert(tk.END, text)
        self._chat_display.see(tk.END)
        self._chat_display.config(state="disabled")

    def _clear_chat(self):
        """Clear chat history and display"""
        self.chatbot.clear_history()
        self._chat_display.config(state="normal")
        self._chat_display.delete("1.0", tk.END)
        self._chat_display.config(state="disabled")
        self._append_chat("Chat cleared. Ready for new conversation.\n\n", "system")

    def _ai_generate_workflow(self, task_override: str = None):
        """Send task to AI and process response into steps"""
        if not self.chatbot.is_ready:
            self._append_chat("⚠️ AI Chatbot not ready.\n\n", "error")
            return

        task = task_override
        if not task:
            task = self._chat_input.get("1.0", tk.END).strip()
            
        # Fallback to last message if empty
        if not task:
            history = self.chatbot.get_history()
            user_msgs = [m["content"] for m in history if m["role"] == "user"]
            if user_msgs:
                task = user_msgs[-1]
        
        if not task:
            self._append_chat("⚠️ Please describe the workflow in the chat first.\n\n", "error")
            if not self._chat_panel_visible: self._toggle_chat_panel()
            return

        self._chat_input.delete("1.0", tk.END)
        self._append_chat(f"You: Generate workflow for: {task}\n", "user")
        self._chat_status_var.set("🤔 Generating...")

        def handle_generate(reply: str):
            try:
                steps_data = self._extract_steps_from_text(reply)
                
                if not steps_data:
                    return

                # Check if we should use existing workflow or create new
                target_wf = None
                is_new = False
                
                if (self._active_workflow and (not self._active_workflow.steps or 
                    messagebox.askyesno("Update Workflow", f"Add generated steps to '{self._active_workflow.name}'? (No will create a new workflow)"))):
                    target_wf = self._active_workflow
                else:
                    target_wf = Workflow(name=f"Gen: {task[:15]}", description=task)
                    self._all_workflows[target_wf.name] = target_wf
                    is_new = True

                for step_data in steps_data:
                    prompt_val = ""
                    name_val = "Step"
                    
                    if isinstance(step_data, str):
                        # Try to extract name from "1. Name: Prompt" or "Name: Prompt"
                        cleaned_step = step_data.strip()
                        if ":" in cleaned_step:
                            parts = cleaned_step.split(":", 1)
                            name_part = parts[0].strip()
                            prompt_val = parts[1].strip()
                            
                            # Strip "1. " or "Step 1: " from name
                            if "." in name_part:
                                name_part = name_part.split(".", 1)[1].strip()
                            if name_part.lower().startswith("step"):
                                # If it's literally just "Step 1", keep it simple
                                pass
                            name_val = name_part[:30]
                        else:
                            prompt_val = cleaned_step
                    elif isinstance(step_data, dict):
                        prompt_val = step_data.get("prompt", step_data.get("text", ""))
                        name_val = step_data.get("name", "Step")
                    
                    if prompt_val:
                        target_wf.add_step(WorkflowStep(name=name_val, prompt=prompt_val))
                
                def update_ui():
                    if not target_wf.steps:
                        return # The Chat Load button will be there as backup

                    self._select_workflow(target_wf.name)
                    # We don't append a message here anymore because 
                    # _on_chat_response (on_response) now always runs first
                    # and adds the bot's reply and the "Load" button.
                    self._chat_status_var.set("🟢 Ready")
                
                self.root.after(0, update_ui)
                
            except Exception as e:
                self.root.after(0, self._append_chat, f"❌ Failed to parse generated steps: {e}\n  Response preview: {reply[:100]}...\n\n", "error")
                self.root.after(0, self._chat_status_var.set, "🟢 Ready")

        self.chatbot.generate_workflow_prompts(task, callback=handle_generate)

    def _on_sync_project(self):
        """Scan project for README, TODO, CHANGELOG and sync to AI"""
        if self._get_selected_editor_key() == "google_ai_studio":
            messagebox.showinfo("Cloud Target", "Google AI Studio is a cloud web workspace. Local project directory sync is not applicable.")
            return
        project_path = self._project_var.get().strip()
        if not project_path or not os.path.isdir(project_path):
            messagebox.showwarning("Sync Project", "Please select a valid project directory first.")
            return
            
        self._append_chat("🔍 Scanning project for context (README, TODO, CHANGELOG)...\n", "system")
        
        context_parts = []
        target_files = [
            "README.md", "TODO.md", "CHANGELOG.md", 
            "decisions.md", "plan.md", "roadmap.md",
            "readme.md", "todo.md", "changelog.md"
        ]
        
        found_any = False
        for filename in target_files:
            file_path = os.path.join(project_path, filename)
            if os.path.isfile(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            context_parts.append(f"--- FILE: {filename} ---\n{content}\n")
                            found_any = True
                except Exception as e:
                    self._append_chat(f"⚠️ Error reading {filename}: {e}\n", "error")
        
        if found_any:
            full_context = "\n".join(context_parts)
            self.chatbot.set_project_context(full_context)
            self._append_chat("✅ Project context synced! AI now knows your README, TODO, and CHANGELOG.\n\n", "system")
            self._chat_status_var.set("🟢 Project Synced")
        else:
            self._append_chat("❓ No README, TODO, or CHANGELOG files found in project root.\n\n", "system")

    def _ai_refine_prompt(self, index: int = 0):
        """Ask AI to refine a specific step's prompt"""
        if not self.chatbot.is_ready:
            self._append_chat("⚠️ AI Chatbot not ready.\n\n", "error")
            return

        if not self._active_workflow or not (0 <= index < len(self._active_workflow.steps)):
            self._append_chat("⚠️ Invalid step selected for refinement.\n\n", "error")
            return

        step = self._active_workflow.steps[index]
        self._append_chat(f"You: Refine Step {index+1}: \"{step.name}\"\n", "user")
        
        if not self._chat_panel_visible:
            self._toggle_chat_panel()

        def handle_refine(reply: str):
            def update_ui():
                self._active_workflow.steps[index].prompt = reply.strip()
                self._render_steps()
                self._append_chat(f"🤖 I've updated Step {index+1} in the workflow editor! ✨\n\n", "bot")
                self._chat_status_var.set("🟢 Ready")
            self.root.after(0, update_ui)

        self.chatbot.refine_prompt(step.prompt, callback=handle_refine)


def main():
    root = tk.Tk()

    # Set icon if available
    try:
        root.iconbitmap(default="")
    except Exception:
        pass

    app = AutoPromptGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
