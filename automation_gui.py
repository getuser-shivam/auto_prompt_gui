#!/usr/bin/env python3
"""
MyCircle Automation GUI
User-friendly graphical interface for the MyCircle automation suite
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import sys
import os
from pathlib import Path
import json
from datetime import datetime

# Import automation modules
try:
    from mycircle_automation import MyCircleAutomation
    from github_automation import GitHubAutomation
    from windsurf_integration import WindsurfIntegration
    AUTOMATION_AVAILABLE = True
except ImportError as e:
    print(f"Import error: {e}")
    print("Please install required packages: pip install -r requirements.txt")
    AUTOMATION_AVAILABLE = False
    
    # Create dummy classes for graceful fallback
    class MyCircleAutomation:
        def __init__(self, *args, **kwargs):
            raise ImportError("MyCircleAutomation not available - check imports")
    
    class GitHubAutomation:
        def __init__(self, *args, **kwargs):
            raise ImportError("GitHubAutomation not available - check imports")
    
    class WindsurfIntegration:
        def __init__(self, *args, **kwargs):
            raise ImportError("WindsurfIntegration not available - check imports")

class AutomationGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MyCircle Automation Suite")
        self.root.geometry("900x700")
        self.root.configure(bg='#f0f0f0')
        
        # Initialize automation instances
        self.automation = None
        self.github_automation = None
        self.windsurf_integration = None
        
        # Setup GUI
        self.setup_styles()
        self.create_widgets()
        self.setup_automation()
        
    def setup_styles(self):
        """Setup ttk styles"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure styles
        style.configure('Title.TLabel', font=('Arial', 16, 'bold'))
        style.configure('Heading.TLabel', font=('Arial', 12, 'bold'))
        style.configure('Success.TLabel', foreground='green')
        style.configure('Error.TLabel', foreground='red')
        style.configure('Info.TLabel', foreground='blue')
        
    def create_widgets(self):
        """Create all GUI widgets"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        # Title
        title_label = ttk.Label(main_frame, text="MyCircle Automation Suite", style='Title.TLabel')
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # Configuration Frame
        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding="10")
        config_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)
        
        # Project Path
        ttk.Label(config_frame, text="Project Path:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.project_path_var = tk.StringVar(value=str(Path.cwd().parent))
        self.project_path_entry = ttk.Entry(config_frame, textvariable=self.project_path_var)
        self.project_path_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        ttk.Button(config_frame, text="Browse", command=self.browse_project_path).grid(row=0, column=2)
        
        # GitHub Token
        ttk.Label(config_frame, text="GitHub Token:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        self.github_token_var = tk.StringVar()
        self.github_token_entry = ttk.Entry(config_frame, textvariable=self.github_token_var, show="*")
        self.github_token_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(10, 0))
        ttk.Button(config_frame, text="Load from .env", command=self.load_env_config).grid(row=1, column=2, pady=(10, 0))
        
        # OpenAI API Key
        ttk.Label(config_frame, text="OpenAI API Key:").grid(row=2, column=0, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        self.openai_key_var = tk.StringVar()
        self.openai_key_entry = ttk.Entry(config_frame, textvariable=self.openai_key_var, show="*")
        self.openai_key_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(10, 0))

        # GLM API Key
        ttk.Label(config_frame, text="GLM API Key:").grid(row=3, column=0, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        self.glm_key_var = tk.StringVar()
        self.glm_key_entry = ttk.Entry(config_frame, textvariable=self.glm_key_var, show="*")
        self.glm_key_entry.grid(row=3, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(10, 0))

        # AI Provider
        ttk.Label(config_frame, text="AI Provider:").grid(row=4, column=0, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        self.ai_provider_var = tk.StringVar(value="openai")
        self.ai_provider_combo = ttk.Combobox(config_frame, textvariable=self.ai_provider_var, values=["openai", "glm", "antigravity"], state="readonly")
        self.ai_provider_combo.grid(row=4, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(10, 0))
        self.ai_provider_combo.bind("<<ComboboxSelected>>", self._update_model_dropdown)

        # AI Model
        ttk.Label(config_frame, text="AI Model:").grid(row=5, column=0, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        self.ai_model_var = tk.StringVar(value="gpt-4")
        self.ai_model_combo = ttk.Combobox(config_frame, textvariable=self.ai_model_var, state="readonly")
        self.ai_model_combo.grid(row=5, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(10, 0))
        self._update_model_dropdown()

        # Flutter SDK Path
        ttk.Label(config_frame, text="Flutter Path:").grid(row=6, column=0, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        self.flutter_path_var = tk.StringVar(value="D:/Download/flutter_windows_3.38.9-stable/flutter/bin/flutter.bat")
        self.flutter_path_entry = ttk.Entry(config_frame, textvariable=self.flutter_path_var)
        self.flutter_path_entry.grid(row=6, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(10, 0))
        ttk.Button(config_frame, text="Browse", command=self.browse_flutter_path).grid(row=6, column=2, pady=(10, 0))
        
        # Action Buttons Frame
        actions_frame = ttk.LabelFrame(main_frame, text="Actions", padding="10")
        actions_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Create buttons in a grid
        buttons = [
            ("🔍 Analyze Project", "analyze", self.analyze_project),
            ("💡 Generate Features", "features", self.generate_features),
            ("🧪 Run Tests", "test", self.run_tests),
            ("📁 Organize Files", "organize", self.organize_files),
            ("📊 Generate Report", "report", self.generate_report),
            ("🏗️ Build App", "build", self.build_app),
            ("▶️ Run App", "run", self.run_app),
            ("🐙 GitHub Stats", "github_stats", self.github_stats),
            ("🌊 Windsurf Setup", "windsurf_setup", self.windsurf_setup),
            ("🚀 Run All", "all", self.run_all_automation),
            ("🩹 Auto-Heal", "heal", self.auto_heal),
            ("🛠️ Self-Repair", "enterprise_repair", self.run_enterprise_repair),
        ]
        
        for i, (text, action, command) in enumerate(buttons):
            row = i // 5
            col = i % 5
            btn = ttk.Button(actions_frame, text=text, command=command)
            btn.grid(row=row, column=col, padx=5, pady=5, sticky=(tk.W, tk.E))
        
        # Feature Implementation Frame
        feature_frame = ttk.LabelFrame(main_frame, text="IDE Agent - Feature Implementation", padding="10")
        feature_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        feature_frame.columnconfigure(1, weight=1)
        
        ttk.Label(feature_frame, text="Request Feature:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.feature_request_var = tk.StringVar()
        self.feature_request_entry = ttk.Entry(feature_frame, textvariable=self.feature_request_var)
        self.feature_request_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        ttk.Button(feature_frame, text="Generate Task", command=self.generate_agent_task).grid(row=0, column=2)

        # Watch Mode Toggle
        self.watch_mode_var = tk.BooleanVar(value=False)
        self.watch_mode_check = ttk.Checkbutton(feature_frame, text="Watch Mode (Auto-Detect Issues)", variable=self.watch_mode_var, command=self.toggle_watch_mode)
        self.watch_mode_check.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(5, 0))
        
        # Configure button grid weights
        for i in range(4):
            actions_frame.columnconfigure(i, weight=1)
        
        # Output Frame
        output_frame = ttk.LabelFrame(main_frame, text="Output", padding="10")
        output_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S))
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(output_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        status_label.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))
        
        # Output text area
        self.output_text = scrolledtext.ScrolledText(output_frame, height=15, wrap=tk.WORD)
        self.output_text.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(output_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
        
        # Menu bar
        self.create_menu()
        
    def create_menu(self):
        """Create menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Load Configuration", command=self.load_env_config)
        file_menu.add_command(label="Save Configuration", command=self.save_config)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        
        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Clear Output", command=self.clear_output)
        tools_menu.add_command(label="Open Project Folder", command=self.open_project_folder)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)
        help_menu.add_command(label="Documentation", command=self.show_documentation)
        help_menu.add_command(label="How to Use Agent AI", command=self.show_agent_help)
        
    def setup_automation(self):
        """Setup automation instances"""
        if not AUTOMATION_AVAILABLE:
            self.log("Automation modules not available. Please check imports and dependencies.", "error")
            self.log("Try running: pip install -r requirements.txt", "info")
            return False
            
        try:
            project_path = self.project_path_var.get()
            github_token = self.github_token_var.get() or None
            openai_key = self.openai_key_var.get() or None
            glm_key = self.glm_key_var.get() or None
            ai_provider = self.ai_provider_var.get() or "openai"
            ai_model = self.ai_model_var.get() or None
            flutter_path = self.flutter_path_var.get() or "flutter"
            
            # Check if project path exists
            if not Path(project_path).exists():
                self.log(f"Project path does not exist: {project_path}", "error")
                return False
            
            # Initialize main automation
            try:
                self.automation = MyCircleAutomation(
                    project_path=project_path, 
                    github_token=github_token, 
                    openai_key=openai_key, 
                    flutter_path=flutter_path, 
                    glm_key=glm_key, 
                    ai_provider=ai_provider,
                    ai_model=ai_model
                )
                self.log("Main automation initialized", "success")
            except Exception as e:
                self.log(f"Error initializing main automation: {e}", "error")
                self.automation = None
            
            # Initialize GitHub automation
            if github_token and github_token.strip():
                try:
                    self.github_automation = GitHubAutomation("getuser-shivam/MyCircle", github_token)
                    self.log("GitHub automation initialized", "success")
                except Exception as e:
                    self.log(f"Error initializing GitHub automation: {e}", "error")
                    self.github_automation = None
            else:
                self.github_automation = None
                self.log("GitHub automation skipped (no token provided)", "info")
            
            # Initialize Windsurf integration
            try:
                self.windsurf_integration = WindsurfIntegration(project_path)
                self.log("Windsurf integration initialized", "success")
            except Exception as e:
                self.log(f"Error initializing Windsurf integration: {e}", "error")
                self.windsurf_integration = None
            
            return True
            
        except Exception as e:
            self.log(f"Error setting up automation: {e}", "error")
            return False
            
    def browse_project_path(self):
        """Browse for project path"""
        path = filedialog.askdirectory(initialdir=self.project_path_var.get())
        if path:
            self.project_path_var.set(path)
            self.setup_automation()

    def browse_flutter_path(self):
        """Browse for Flutter executable"""
        path = filedialog.askopenfilename(
            title="Select flutter.bat",
            initialdir=os.path.dirname(self.flutter_path_var.get()),
            filetypes=[("Executable files", "*.bat *.exe"), ("All files", "*.*")]
        )
        if path:
            self.flutter_path_var.set(path)
            self.setup_automation()
            
    def load_env_config(self):
        """Load configuration from .env file"""
        env_file = Path(".env")
        if not env_file.exists():
            env_file = Path(".env.example")
            
        if env_file.exists():
            try:
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            if '=' in line:
                                key, value = line.split('=', 1)
                                if key == 'GITHUB_TOKEN':
                                    self.github_token_var.set(value)
                                elif key == 'OPENAI_API_KEY':
                                    self.openai_key_var.set(value)
                                elif key == 'GLM_KEY':
                                    self.glm_key_var.set(value)
                                elif key == 'AI_PROVIDER':
                                    self.ai_provider_var.set(value)
                                    self._update_model_dropdown()
                                elif key == 'AI_MODEL':
                                    self.ai_model_var.set(value)
                                elif key == 'PROJECT_PATH':
                                    self.project_path_var.set(value)
                                elif key == 'FLUTTER_PATH':
                                    self.flutter_path_var.set(value)
                
                self.setup_automation()
                self.log("Configuration loaded from .env file", "success")
                
            except Exception as e:
                self.log(f"Error loading configuration: {e}", "error")
        else:
            self.log("No .env file found", "info")
            
    def save_config(self):
        """Save current configuration to .env file"""
        try:
            with open('.env', 'w') as f:
                f.write("# MyCircle Automation Configuration\n")
                f.write(f"GITHUB_TOKEN={self.github_token_var.get()}\n")
                f.write(f"OPENAI_API_KEY={self.openai_key_var.get()}\n")
                f.write(f"GLM_KEY={self.glm_key_var.get()}\n")
                f.write(f"AI_PROVIDER={self.ai_provider_var.get()}\n")
                f.write(f"AI_MODEL={self.ai_model_var.get()}\n")
                f.write(f"PROJECT_PATH={self.project_path_var.get()}\n")
                f.write(f"FLUTTER_PATH={self.flutter_path_var.get()}\n")
                
            self.log("Configuration saved to .env file", "success")
            
        except Exception as e:
            self.log(f"Error saving configuration: {e}", "error")
            
    def log(self, message, level="info"):
        """Log message to output area"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}\n"
        
        self.output_text.insert(tk.END, formatted_message)
        self.output_text.see(tk.END)
        
        # Update status bar
        self.status_var.set(message)
        
        # Color coding
        if level == "error":
            self.output_text.tag_add("error", f"end-2l", f"end-1l")
            self.output_text.tag_config("error", foreground="red")
        elif level == "success":
            self.output_text.tag_add("success", f"end-2l", f"end-1l")
            self.output_text.tag_config("success", foreground="green")
        elif level == "info":
            self.output_text.tag_add("info", f"end-2l", f"end-1l")
            self.output_text.tag_config("info", foreground="blue")
            
    def clear_output(self):
        """Clear output area"""
        self.output_text.delete(1.0, tk.END)
        self.log("Output cleared")
        
    def set_progress(self, value):
        """Set progress bar value"""
        self.progress_var.set(value)
        self.root.update_idletasks()
        
    def run_in_thread(self, func, *args, **kwargs):
        """Run function in separate thread"""
        def wrapper():
            try:
                func(*args, **kwargs)
            except Exception as e:
                self.log(f"Error: {e}", "error")
            finally:
                self.set_progress(0)
                
        thread = threading.Thread(target=wrapper)
        thread.daemon = True
        thread.start()
        
    def analyze_project(self):
        """Analyze project"""
        if not self.automation:
            self.log("Please setup automation first", "error")
            self.setup_automation()  # Try to setup automatically
            if not self.automation:
                return
            
        self.run_in_thread(self._analyze_project)
        
    def _analyze_project(self):
        """Analyze project in thread"""
        self.log("Starting project analysis...")
        self.set_progress(20)
        
        try:
            analysis = self.automation.analyze_project()
            self.set_progress(60)
            
            # Display results
            self.log(f"✅ Project Analysis Complete:", "success")
            self.log(f"   Name: {analysis.name}")
            self.log(f"   Flutter Version: {analysis.flutter_version}")
            self.log(f"   Screens: {analysis.screen_count}")
            self.log(f"   Widgets: {analysis.widget_count}")
            self.log(f"   Providers: {analysis.provider_count}")
            self.log(f"   Total Lines: {analysis.total_lines}")
            self.log(f"   Complexity Score: {analysis.complexity_score:.1f}/100")
            self.log(f"   Last Modified: {analysis.last_modified}")
            
            if analysis.issues:
                self.log(f"   Issues Found: {len(analysis.issues)}")
                for issue in analysis.issues[:5]:
                    self.log(f"     - {issue}")
                    
            if analysis.suggestions:
                self.log(f"   Suggestions: {len(analysis.suggestions)}")
                for suggestion in analysis.suggestions[:5]:
                    self.log(f"     - {suggestion}")
                    
            self.set_progress(100)
            self.log("Project analysis completed successfully!", "success")
            
        except Exception as e:
            self.log(f"Error during analysis: {e}", "error")
            
    def generate_features(self):
        """Generate feature ideas"""
        if not self.automation:
            self.log("Please setup automation first", "error")
            self.setup_automation()  # Try to setup automatically
            if not self.automation:
                return
            
        self.run_in_thread(self._generate_features)
        
    def _generate_features(self):
        """Generate features in thread"""
        self.log("Generating feature ideas...")
        self.set_progress(30)
        
        try:
            features = self.automation.generate_feature_ideas()
            self.set_progress(70)
            
            self.log(f"✅ Generated {len(features)} feature ideas:", "success")
            for i, feature in enumerate(features, 1):
                self.log(f"   {i}. {feature.title} ({feature.priority})")
                self.log(f"      {feature.description}")
                self.log(f"      Estimated: {feature.estimated_hours}h")
                if feature.dependencies:
                    self.log(f"      Dependencies: {', '.join(feature.dependencies)}")
                self.log("")
                
            self.set_progress(100)
            self.log("Feature generation completed!", "success")
            
        except Exception as e:
            self.log(f"Error generating features: {e}", "error")
            
    def run_tests(self):
        """Run tests"""
        if not self.automation:
            self.log("Please setup automation first", "error")
            self.setup_automation()  # Try to setup automatically
            if not self.automation:
                return
            
        self.run_in_thread(self._run_tests)
        
    def _run_tests(self):
        """Run tests in thread"""
        self.log("Running tests...")
        self.set_progress(20)
        
        try:
            results = self.automation.run_tests()
            self.set_progress(60)
            
            self.log("✅ Test Results:", "success")
            for test_type, result in results.items():
                status = result['status']
                icon = "✅" if status == "passed" else "❌"
                self.log(f"   {icon} {test_type}: {status}")
                
                if result.get('output'):
                    # Show first few lines of output
                    output_lines = result['output'].split('\n')[:5]
                    for line in output_lines:
                        if line.strip():
                            self.log(f"     {line}")
                            
            self.set_progress(100)
            self.log("Test execution completed!", "success")
            
        except Exception as e:
            self.log(f"Error running tests: {e}", "error")
            
    def organize_files(self):
        """Organize files"""
        if not self.automation:
            self.log("Please setup automation first", "error")
            self.setup_automation()  # Try to setup automatically
            if not self.automation:
                return
            
        self.run_in_thread(self._organize_files)
        
    def _organize_files(self):
        """Organize files in thread"""
        self.log("Organizing project files...")
        self.set_progress(30)
        
        try:
            organization = self.automation.organize_files()
            self.set_progress(70)
            
            self.log("✅ File Organization Results:", "success")
            self.log(f"   Files Cleaned: {len(organization['cleaned'])}")
            self.log(f"   Files Organized: {len(organization['organized'])}")
            self.log(f"   Errors: {len(organization['errors'])}")
            
            if organization['errors']:
                self.log("   Errors encountered:")
                for error in organization['errors'][:5]:
                    self.log(f"     - {error}")
                    
            self.set_progress(100)
            self.log("File organization completed!", "success")
            
        except Exception as e:
            self.log(f"Error organizing files: {e}", "error")
            
    def generate_report(self):
        """Generate report"""
        if not self.automation:
            self.log("Please setup automation first", "error")
            self.setup_automation()  # Try to setup automatically
            if not self.automation:
                return
            
        self.run_in_thread(self._generate_report)
        
    def _generate_report(self):
        """Generate report in thread"""
        self.log("Generating comprehensive report...")
        self.set_progress(20)
        
        try:
            report = self.automation.generate_report()
            self.set_progress(80)
            
            self.log("✅ Report generated successfully!", "success")
            self.log(f"   Report saved to: automation_report.md")
            self.log("")
            self.log("Report Summary:")
            self.log("   - Project analysis completed")
            self.log("   - Feature ideas generated")
            self.log("   - Test results included")
            self.log("   - File organization results")
            self.log("   - GitHub statistics (if available)")
            
            self.set_progress(100)
            self.log("Open automation_report.md to view the full report", "info")
            
        except Exception as e:
            self.log(f"Error generating report: {e}", "error")
            
    def build_app(self):
        """Build the application"""
        if not self.automation:
            self.log("Please setup automation first", "error")
            self.setup_automation()
            if not self.automation:
                return

        self.run_in_thread(self._build_app)

    def _build_app(self):
        """Build app in thread"""
        self.log("Starting application build (Windows)...")
        self.set_progress(20)

        try:
            result = self.automation.build_app(platform="windows")
            self.set_progress(100)

            if result["status"] == "passed":
                self.log("✅ Build completed successfully!", "success")
            else:
                self.log("❌ Build failed", "error")
                self.log(result["output"])

        except Exception as e:
            self.log(f"Error during build: {e}", "error")

    def run_app(self):
        """Run the application"""
        if not self.automation:
            self.log("Please setup automation first", "error")
            self.setup_automation()
            if not self.automation:
                return

        self.run_in_thread(self._run_app)

    def _run_app(self):
        """Run app in thread"""
        self.log("Launching application on Windows...")
        self.set_progress(50)

        try:
            result = self.automation.run_app(platform="windows")
            self.set_progress(100)

            if result["status"] == "running":
                self.log(f"✅ {result['message']}", "success")
            else:
                self.log("❌ Failed to launch app", "error")
                if "output" in result:
                    self.log(result["output"])

        except Exception as e:
            self.log(f"Error during launch: {e}", "error")

    def run_enterprise_repair(self):
        """Run Enterprise Self-Repair"""
        if not self.automation:
            self.log("Please setup automation first", "error")
            self.setup_automation()
            if not self.automation:
                return

        def job():
            self.log("🚀 Starting Enterprise Self-Repair...")
            self.set_progress(20)
            
            try:
                from enterprise_repair import EnterpriseRepair
                repairer = EnterpriseRepair(self.project_path_var.get())
                
                errors = repairer.run_analysis()
                self.set_progress(40)
                
                if errors:
                    self.log(f"Found {len(errors)} issues. Applying auto-repairs...", "info")
                    repairer.repair_missing_imports(errors)
                    self.set_progress(70)
                    
                    # Re-run after repair
                    final_errors = repairer.run_analysis()
                    repairer.generate_repair_report(final_errors)
                    self.set_progress(100)
                    
                    self.log(f"✅ Enterprise repair finished. {len(final_errors)} issues remaining.", "success")
                    self.log("📊 Check .windsurf/repair_report.md for details", "info")
                else:
                    self.set_progress(100)
                    self.log("✅ No issues found to repair!", "success")
            except Exception as e:
                self.log(f"Error during enterprise repair: {e}", "error")

        self.run_in_thread(job)

    def auto_heal(self):
        """Run auto-heal"""
        if not self.automation:
            self.log("Please setup automation first", "error")
            self.setup_automation()
            if not self.automation:
                return

        self.run_in_thread(self._auto_heal)

    def _auto_heal(self):
        """Auto-heal in thread"""
        self.log("Starting Auto-Heal process...")
        self.set_progress(30)

        try:
            result = self.automation.auto_heal()
            self.set_progress(100)
            
            self.log("✅ Auto-Heal task prepared!", "success")
            self.log(f"   Task File: {result['task_file']}")
            self.log("📋 Prompt ready to copy", "info")
            
            # Show dialog with prompt and copy button
            self.show_prompt_dialog("Auto-Heal Prompt", result['prompt'])

        except Exception as e:
            self.log(f"Error during auto-heal: {e}", "error")

    def generate_agent_task(self):
        """Generate a task for the IDE agent"""
        prompt = self.feature_request_var.get().strip()
        if not prompt:
            messagebox.showwarning("Warning", "Please enter a feature request first.")
            return

        if not self.automation:
            self.log("Please setup automation first", "error")
            self.setup_automation()
            if not self.automation:
                return

        self.run_in_thread(self._generate_agent_task, prompt)

    def _generate_agent_task(self, prompt):
        """Generate agent task in thread"""
        self.log(f"Preparing agent task for: {prompt}")
        self.set_progress(50)

        try:
            result = self.automation.request_agent_help(prompt)
            self.set_progress(100)
            
            self.log("✅ Feature task prepared!", "success")
            self.log(f"   Task File: {result['task_file']}")
            
            # Show dialog with prompt
            self.show_prompt_dialog("Implement Feature Prompt", result['prompt'])

        except Exception as e:
            self.log(f"Error preparing task: {e}", "error")

    def show_prompt_dialog(self, title, prompt):
        """Show a dialog with the prompt and a copy to clipboard button"""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("500x300")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Copy this prompt to your IDE Agent (Windsurf):", font=('Arial', 10, 'bold')).pack(pady=(0, 10))
        
        text_area = scrolledtext.ScrolledText(frame, height=8, wrap=tk.WORD)
        text_area.insert(tk.END, prompt)
        text_area.configure(state='disabled')
        text_area.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        def copy_to_clipboard():
            self.root.clipboard_clear()
            self.root.clipboard_append(prompt)
            messagebox.showinfo("Success", "Prompt copied to clipboard!")
            dialog.destroy()

        ttk.Button(frame, text="Copy & Close", command=copy_to_clipboard).pack()

    def toggle_watch_mode(self):
        """Toggle watch mode on/off"""
        if self.watch_mode_var.get():
            self.log("Watch Mode enabled. Monitoring for issues...", "info")
            self.start_watching()
        else:
            self.log("Watch Mode disabled.", "info")

    def start_watching(self):
        """Background loop for watching the project"""
        if not self.watch_mode_var.get():
            return

        def watch_loop():
            import time
            while self.watch_mode_var.get():
                try:
                    # Run a quick check
                    if self.automation:
                        report = self.automation.run_tests()
                        lint = report.get("linting", {})
                        if lint.get("status") == "failed":
                            self.log("⚠️ Issues detected in Watch Mode!", "error")
                            # Automatically trigger auto-heal logic in the main thread
                            self.root.after(0, self.auto_heal)
                            # Sleep longer if we found issues to avoid spamming
                            time.sleep(60) 
                        else:
                            time.sleep(30) # Check every 30 seconds if clean
                except Exception as e:
                    self.log(f"Watch Error: {e}", "error")
                    time.sleep(10)

        thread = threading.Thread(target=watch_loop)
        thread.daemon = True
        thread.start()

    def show_agent_help(self):
        """Show help for the Agent Bridge feature"""
        help_text = """How to use AI without a Paid Key:

1. Use 'Request Feature' or 'Auto-Heal' tools.
2. The app will generate a technical 'Task' file in .windsurf/tasks/
3. A prompt will be provided. Click 'Copy & Close'.
4. Paste the prompt into your IDE's AI chat (Windsurf / Cascade / VS Code Copilot Chat).
5. The IDE Agent will read the task file and perform the work!

This 'Bridge' allows you to use the powerful AI already built into your editor to automate MyCircle development for free."""
        messagebox.showinfo("IDE Agent Bridge Help", help_text)

    def github_stats(self):
        """Get GitHub statistics"""
        if not self.github_automation:
            self.log("GitHub token not configured", "error")
            # Try to setup with current token
            if self.github_token_var.get().strip():
                self.setup_automation()
                if not self.github_automation:
                    return
            else:
                self.log("Please enter a GitHub token in the configuration", "info")
                return
            
        self.run_in_thread(self._github_stats)
        
    def _github_stats(self):
        """Get GitHub stats in thread"""
        self.log("Fetching GitHub repository statistics...")
        self.set_progress(30)
        
        try:
            stats = self.github_automation.get_repository_stats()
            self.set_progress(70)
            
            if 'error' in stats:
                self.log(f"Error: {stats['error']}", "error")
                return
                
            self.log("✅ GitHub Repository Statistics:", "success")
            self.log(f"   Repository: {stats['full_name']}")
            self.log(f"   Stars: {stats['stars']}")
            self.log(f"   Forks: {stats['forks']}")
            self.log(f"   Watchers: {stats['watchers']}")
            self.log(f"   Open Issues: {stats['open_issues']}")
            self.log(f"   Language: {stats['language']}")
            self.log(f"   Size: {stats['size']} KB")
            
            if stats.get('recent_commits'):
                self.log(f"   Recent Commits: {len(stats['recent_commits'])}")
                
            if stats.get('contributors'):
                self.log(f"   Contributors: {len(stats['contributors'])}")
                
            self.set_progress(100)
            self.log("GitHub statistics retrieved successfully!", "success")
            
        except Exception as e:
            self.log(f"Error fetching GitHub stats: {e}", "error")
            
    def windsurf_setup(self):
        """Setup Windsurf integration"""
        if not self.windsurf_integration:
            self.log("Windsurf integration not available", "error")
            self.setup_automation()  # Try to setup automatically
            if not self.windsurf_integration:
                return
            
        self.run_in_thread(self._windsurf_setup)
        
    def _windsurf_setup(self):
        """Setup Windsurf in thread"""
        self.log("Setting up Windsurf integration...")
        self.set_progress(40)
        
        try:
            success = self.windsurf_integration.setup_windsurf_workspace()
            self.set_progress(80)
            
            if success:
                self.log("✅ Windsurf workspace setup completed!", "success")
                self.log("   - .windsurf directory configured")
                self.log("   - Development instructions created")
                self.log("   - AI integration ready")
            else:
                self.log("❌ Windsurf setup failed", "error")
                
            self.set_progress(100)
            
        except Exception as e:
            self.log(f"Error setting up Windsurf: {e}", "error")
            
    def run_all_automation(self):
        """Run all automation tasks"""
        self.run_in_thread(self._run_all_automation)
        
    def _run_all_automation(self):
        """Run all automation in thread"""
        self.log("🚀 Running complete automation suite...", "info")
        self.set_progress(5)
        
        # Ensure automation is setup
        if not self.automation:
            self.log("Setting up automation first...")
            if not self.setup_automation():
                self.log("Failed to setup automation", "error")
                return
        
        try:
            # Analyze project
            self.log("Step 1: Analyzing project...")
            self.set_progress(15)
            analysis = self.automation.analyze_project()
            self.log(f"✅ Analysis complete - Complexity: {analysis.complexity_score:.1f}/100", "success")
            self.set_progress(25)
            
            # Generate features
            self.log("Step 2: Generating features...")
            features = self.automation.generate_feature_ideas()
            self.log(f"✅ Generated {len(features)} feature ideas", "success")
            self.set_progress(35)
            
            # Run tests
            self.log("Step 3: Running tests...")
            results = self.automation.run_tests()
            passed_tests = sum(1 for r in results.values() if r['status'] == 'passed')
            self.log(f"✅ Tests complete - {passed_tests}/{len(results)} passed", "success")
            self.set_progress(45)
            
            # Organize files
            self.log("Step 4: Organizing files...")
            organization = self.automation.organize_files()
            self.log(f"✅ File organization complete - {len(organization['organized'])} files processed", "success")
            self.set_progress(55)
            
            # Generate report
            self.log("Step 5: Generating report...")
            self.automation.generate_report()
            self.log("✅ Report generated - automation_report.md", "success")
            self.set_progress(70)
            
            # GitHub stats (if available)
            if self.github_automation:
                self.log("Step 6: Fetching GitHub stats...")
                try:
                    stats = self.github_automation.get_repository_stats()
                    self.log(f"✅ GitHub stats - {stats['stars']} stars, {stats['forks']} forks", "success")
                except Exception as e:
                    self.log(f"⚠️ GitHub stats failed: {e}", "error")
            
            # Windsurf setup (if available)
            if self.windsurf_integration:
                self.log("Step 7: Setting up Windsurf...")
                try:
                    success = self.windsurf_integration.setup_windsurf_workspace()
                    if success:
                        self.log("✅ Windsurf setup complete", "success")
                    else:
                        self.log("⚠️ Windsurf setup failed", "error")
                except Exception as e:
                    self.log(f"⚠️ Windsurf setup failed: {e}", "error")
                
            self.set_progress(100)
            self.log("🎉 Complete automation suite finished successfully!", "success")
            
        except Exception as e:
            self.log(f"Error in automation suite: {e}", "error")
            
    def open_project_folder(self):
        """Open project folder in file explorer"""
        import subprocess
        import platform
        
        project_path = self.project_path_var.get()
        try:
            if platform.system() == "Windows":
                subprocess.run(['explorer', project_path])
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(['open', project_path])
            else:  # Linux
                subprocess.run(['xdg-open', project_path])
                
            self.log(f"Opened project folder: {project_path}")
            
        except Exception as e:
            self.log(f"Error opening folder: {e}", "error")

    def _update_model_dropdown(self, event=None):
        """Update the model dropdown based on selected provider"""
        provider = self.ai_provider_var.get()
        
        models = {
            "openai": ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
            "glm": ["glm-5", "glm-4", "glm-4-air"],
            "antigravity": [
                "antigravity-v1", 
                "Gemini 3 Pro (High)", 
                "Gemini 3 Pro (Low)", 
                "Gemini 3 Flash",
                "Claude Sonnet 4.5", 
                "Claude Sonnet 4.5 (Thinking)", 
                "Claude Opus 4.5 (Thinking)", 
                "Claude Opus 4.6 (Thinking)",
                "GPT-OSS 120B (Medium)"
            ]
        }
        
        provider_models = models.get(provider, ["default"])
        self.ai_model_combo['values'] = provider_models
        
        # Set default if current selection not in new list
        current_model = self.ai_model_var.get()
        if current_model not in provider_models:
            self.ai_model_var.set(provider_models[0])
            
    def show_about(self):
        """Show about dialog"""
        about_text = """MyCircle Automation Suite v1.0

A comprehensive automation tool for MyCircle Flutter project development.

Features:
• Project Analysis & Complexity Scoring
• AI-Powered Feature Generation
• Automated Testing & Quality Assurance
• GitHub Integration & Management
• File Organization & Cleanup
• Windsurf AI Integration

Created with ❤️ for automated development"""
        
        messagebox.showinfo("About MyCircle Automation", about_text)
        
    def show_documentation(self):
        """Show documentation"""
        try:
            import webbrowser
            readme_path = Path("README.md").absolute()
            if readme_path.exists():
                webbrowser.open(f"file://{readme_path}")
            else:
                messagebox.showinfo("Documentation", "Please check the README.md file for detailed documentation.")
        except Exception as e:
            self.log(f"Error opening documentation: {e}", "error")

def main():
    """Main function to run the GUI"""
    root = tk.Tk()
    app = AutomationGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
