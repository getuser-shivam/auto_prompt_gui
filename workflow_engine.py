#!/usr/bin/env python3
"""
Workflow Engine for Auto-Prompt GUI
Sequences prompts one-after-another with pause/resume/cancel controls.
"""

import json
import time
import threading
import copy
import os
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class WorkflowStep:
    """A single step in a workflow"""

    def __init__(self, name: str, prompt: str, delay_after: float = 3.0,
                 condition: str = "", enabled: bool = True):
        self.name = name
        self.prompt = prompt
        self.delay_after = delay_after  # seconds to wait after this step
        self.condition = condition  # optional condition string
        self.enabled = enabled
        self.status = "pending"  # pending | running | completed | failed | skipped
        self.result = ""
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.success_count: int = 0
        self.failure_count: int = 0
        self.retry_count: int = 0
        self.max_retries: int = 3
        self.last_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "prompt": self.prompt,
            "delay_after": self.delay_after,
            "condition": self.condition,
            "enabled": self.enabled,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowStep":
        step = cls(
            name=data.get("name", "Untitled Step"),
            prompt=data.get("prompt", ""),
            delay_after=data.get("delay_after", 3.0),
            condition=data.get("condition", ""),
            enabled=data.get("enabled", True),
        )
        step.success_count = data.get("success_count", 0)
        step.failure_count = data.get("failure_count", 0)
        return step


class Workflow:
    """A complete workflow with ordered steps"""

    def __init__(self, name: str, description: str = "", steps: List[WorkflowStep] = None):
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = steps or []
        self.variables: Dict[str, str] = {}
        self.created_at = datetime.now().isoformat()
        self.filepath: Optional[str] = None

    def add_step(self, step: WorkflowStep):
        self.steps.append(step)

    def remove_step(self, index: int):
        if 0 <= index < len(self.steps):
            self.steps.pop(index)

    def move_step(self, from_idx: int, to_idx: int):
        if 0 <= from_idx < len(self.steps) and 0 <= to_idx < len(self.steps):
            step = self.steps.pop(from_idx)
            self.steps.insert(to_idx, step)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "variables": self.variables,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Workflow":
        wf = cls(
            name=data.get("name", "Untitled"),
            description=data.get("description", ""),
        )
        wf.variables = data.get("variables", {})
        wf.created_at = data.get("created_at", datetime.now().isoformat())
        for step_data in data.get("steps", []):
            wf.add_step(WorkflowStep.from_dict(step_data))
        return wf

    def resolve_prompt(self, step: WorkflowStep) -> str:
        """Replace template variables in prompt text"""
        prompt = step.prompt
        for key, value in self.variables.items():
            prompt = prompt.replace(f"{{{key}}}", value)
        return prompt


class WorkflowEngine:
    """Engine that executes workflows step by step"""

    def __init__(self):
        self._current_workflow: Optional[Workflow] = None
        self._current_step_index: int = -1
        self._running = False
        self._paused = False
        self._cancel_requested = False
        self._lock = threading.Lock()
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused initially
        self._thread: Optional[threading.Thread] = None

        # Step execution and retry metrics
        self.step_retry_limit: int = 3
        self.auto_retry_failed_steps: bool = True
        self.total_steps_executed: int = 0
        self.total_steps_succeeded: int = 0
        self.total_steps_failed: int = 0
        self.total_step_retries: int = 0

        # Step retry and recovery callbacks
        self.on_step_retry: Optional[Callable[[int, WorkflowStep, int, int, str], None]] = None
        self.on_step_failure_recovery: Optional[Callable[[int, WorkflowStep, str], None]] = None

        # Looping state
        self.loop_mode = False
        self.loop_interval = 120.0  # default 2 mins
        self._loop_countdown = 0.0
        
        # Stop every X steps logic
        self.stop_every_x = 0  # 0 = disabled
        self._steps_since_last_stop = 0

        # Callbacks
        self.on_step_start: Optional[Callable[[int, WorkflowStep], None]] = None
        self.on_step_complete: Optional[Callable[[int, WorkflowStep, str], None]] = None
        self.on_workflow_done: Optional[Callable[[Workflow, str], None]] = None
        self.on_error: Optional[Callable[[int, WorkflowStep, str], None]] = None
        self.on_progress: Optional[Callable[[int, int, float], None]] = None

        # The send_prompt function — set by the GUI to bridge to the editor
        self.send_prompt_fn: Optional[Callable[[str], str]] = None

        # Auto-interact mode: send AND wait for AI completion
        self.send_and_wait_fn: Optional[Callable[[str], str]] = None

        self.on_loop_wait: Optional[Callable[[float], None]] = None

        # Global delay override (non-persistent, set by GUI per run)
        self.global_delay_override: Optional[float] = None

        # Built-in workflows
        self.builtin_workflows = self._create_builtin_workflows()

    @staticmethod
    def is_step_failure(result: str) -> bool:
        """Determines if the step result string indicates a failure"""
        if not result:
            return False
        r_lower = result.lower()
        failure_markers = [
            "❌",
            "error:",
            "unexpected error",
            "please click send manually",
            "⚠️ timed out",
            "timed out after",
            "quota exceeded",
            "resource has been exhausted",
            "rate limit",
            "web uia injection failed",
            "failed to paste",
            "failed to find send button",
            "exception:",
        ]
        return any(marker in r_lower for marker in failure_markers)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def current_step_index(self) -> int:
        return self._current_step_index

    def start(self, workflow: Workflow):
        """Start executing a workflow in a background thread"""
        if self._running:
            raise RuntimeError("A workflow is already running")

        self._current_workflow = workflow
        self._current_step_index = -1
        self._running = True
        self._paused = False
        self._cancel_requested = False
        self._pause_event.set()

        # Reset all step statuses
        for step in workflow.steps:
            step.status = "pending"
            step.result = ""
            step.started_at = None
            step.completed_at = None
            step.retry_count = 0

        self._thread = threading.Thread(target=self._run_workflow, daemon=True)
        self._thread.start()

    def pause(self):
        """Pause the current workflow"""
        with self._lock:
            if self._running and not self._paused:
                self._paused = True
                self._pause_event.clear()

    def resume(self):
        """Resume a paused workflow"""
        with self._lock:
            if self._running and self._paused:
                self._paused = False
                self._pause_event.set()

    def cancel(self):
        """Cancel the current workflow"""
        with self._lock:
            self._cancel_requested = True
            self.loop_mode = False  # disable loop on cancel
            self._paused = False
            self._pause_event.set()  # unblock if paused

    def _run_workflow(self):
        """Main workflow execution loop with automatic retry of failed steps before advancing"""
        workflow = self._current_workflow
        
        while True:
            total_steps = len(workflow.steps)
            
            try:
                i = 0
                while i < total_steps:
                    step = workflow.steps[i]

                    # Check cancel
                    if self._cancel_requested:
                        step.status = "skipped"
                        i += 1
                        continue

                    # Wait if paused
                    self._pause_event.wait()

                    if self._cancel_requested:
                        step.status = "skipped"
                        i += 1
                        continue

                    # Skip disabled steps
                    if not step.enabled:
                        step.status = "skipped"
                        i += 1
                        continue

                    # Start step
                    self._current_step_index = i
                    step.status = "running"
                    step.started_at = datetime.now()

                    if self.on_step_start:
                        try:
                            self.on_step_start(i, step)
                        except Exception:
                            pass

                    # Handle "Stop every X steps"
                    if self.stop_every_x > 0:
                        self._steps_since_last_stop += 1
                        if self._steps_since_last_stop >= self.stop_every_x:
                            self._steps_since_last_stop = 0
                            self.pause()
                            logger.info(f"Automatically paused after {self.stop_every_x} steps")

                    # Progress callback
                    if self.on_progress:
                        progress = (i / total_steps) * 100
                        try:
                            self.on_progress(i, total_steps, progress)
                        except Exception:
                            pass

                    # Execute the prompt
                    resolved_prompt = workflow.resolve_prompt(step)
                    failed = False
                    result = ""

                    try:
                        self.total_steps_executed += 1
                        if self.send_and_wait_fn:
                            result = self.send_and_wait_fn(resolved_prompt)
                        elif self.send_prompt_fn:
                            result = self.send_prompt_fn(resolved_prompt)
                        else:
                            result = f"[Dry Run] Prompt queued: {resolved_prompt[:80]}..."

                        # Check if result indicates failure
                        failed = self.is_step_failure(result)

                    except Exception as e:
                        failed = True
                        result = f"Exception: {e}"

                    if failed:
                        step.failure_count += 1
                        self.total_steps_failed += 1
                        step.last_error = result
                        logger.warning(f"Step {i + 1} ({step.name}) FAILED: {result}")

                        # Check if we should rerun this step before proceeding to the next step
                        if self.auto_retry_failed_steps and step.retry_count < self.step_retry_limit:
                            step.retry_count += 1
                            self.total_step_retries += 1
                            logger.info(f"🔄 Retrying Step {i + 1} (Attempt {step.retry_count}/{self.step_retry_limit})...")

                            if self.on_step_retry:
                                try:
                                    self.on_step_retry(i, step, step.retry_count, self.step_retry_limit, result)
                                except Exception:
                                    pass

                            if self.on_step_failure_recovery:
                                try:
                                    self.on_step_failure_recovery(i, step, result)
                                except Exception:
                                    pass

                            time.sleep(3.0)  # Recovery backoff
                            # DO NOT increment i! Re-run this exact step!
                            continue
                        else:
                            # Step failed permanently after max retries
                            step.status = "failed"
                            step.result = result or "Failed"
                            step.completed_at = datetime.now()

                            if self.on_error:
                                try:
                                    self.on_error(i, step, result)
                                except Exception:
                                    pass

                            logger.error(f"Step {i + 1} permanently failed after {step.retry_count} retries. Pausing workflow.")
                            self.pause()
                            break
                    else:
                        # Step SUCCEEDED!
                        step.status = "completed"
                        step.result = result or "Done"
                        step.success_count += 1
                        self.total_steps_succeeded += 1
                        step.retry_count = 0  # reset for next loop iteration
                        step.completed_at = datetime.now()

                        if self.on_step_complete:
                            try:
                                self.on_step_complete(i, step, result)
                            except Exception:
                                pass

                    # Delay between steps (cooldown)
                    delay = self.global_delay_override if self.global_delay_override is not None else step.delay_after

                    # When smart completion (send_and_wait_fn) is active, prompt completion is dynamically detected!
                    # Legacy blind delays (> 10s like 600s/700s) must NOT delay execution.
                    if self.send_and_wait_fn and delay and delay > 10.0:
                        logger.info(f"Smart completion active: bypassing blind {delay}s delay to start next step without wasting time.")
                        delay = 0.0

                    if i < total_steps - 1 and delay > 0:
                        delay_end = time.time() + delay
                        while time.time() < delay_end:
                            if self._cancel_requested:
                                break
                            remaining = max(0, delay_end - time.time())
                            if self.on_loop_wait:
                                self.on_loop_wait(remaining)
                            time.sleep(0.5)
                            self._pause_event.wait()

                    # Advance to next step!
                    i += 1
                
                # Workflow loop run complete
                if not self.loop_mode or self._cancel_requested:
                    break
                
                # Handle Looping
                if self.on_workflow_done:
                    try:
                        self.on_workflow_done(workflow, "looping")
                    except Exception:
                        pass
                
                # Reset steps for next run
                for step in workflow.steps:
                    step.status = "pending"
                
                # Wait for interval
                self._loop_countdown = self.loop_interval
                while self._loop_countdown > 0:
                    if self._cancel_requested or not self.loop_mode:
                        break
                    
                    if self.on_loop_wait:
                        self.on_loop_wait(self._loop_countdown)
                    
                    sleep_time = min(1.0, self._loop_countdown)
                    time.sleep(sleep_time)
                    self._loop_countdown -= sleep_time
                
                if self._cancel_requested or not self.loop_mode:
                    break

            except Exception as e:
                logger.error(f"Workflow execution error: {e}")
                if self.on_workflow_done:
                    try:
                        self.on_workflow_done(workflow, f"error: {e}")
                    except Exception:
                        pass
                break

        # Final completion
        status = "cancelled" if self._cancel_requested else "completed"
        if self.on_progress:
            try:
                self.on_progress(len(workflow.steps), len(workflow.steps), 100)
            except Exception:
                pass

        if self.on_workflow_done:
            try:
                self.on_workflow_done(workflow, status)
            except Exception:
                pass

        self._running = False
        self._paused = False
        self._current_step_index = -1

    def _create_builtin_workflows(self) -> Dict[str, Workflow]:
        """Create built-in preset workflows"""
        workflows = {}

        # === Full Feature Development ===
        wf = Workflow(
            name="Full Feature Dev",
            description="End-to-end feature development: analyze → model → UI → state → test"
        )
        wf.add_step(WorkflowStep(
            name="1. Analyze Project",
            prompt=(
                "Analyze the project at {project_path}. "
                "Review the folder structure, existing screens, providers, models, and services. "
                "Summarize what the app does and list all existing features."
            ),
            delay_after=5.0,
        ))
        wf.add_step(WorkflowStep(
            name="2. Design Feature",
            prompt=(
                "Based on the project analysis, design the '{feature_name}' feature. "
                "Create a detailed implementation plan including:\n"
                "- Data models needed\n"
                "- API endpoints / Supabase tables\n"
                "- UI screens and widgets\n"
                "- State management (Provider/Riverpod)\n"
                "- Navigation flow\n"
                "Write the plan as a markdown checklist."
            ),
            delay_after=5.0,
        ))
        wf.add_step(WorkflowStep(
            name="3. Create Data Models",
            prompt=(
                "Implement the data models for '{feature_name}' as designed in the plan. "
                "Create Dart model classes in lib/models/ with:\n"
                "- JSON serialization (fromJson / toJson)\n"
                "- copyWith method\n"
                "- Proper type annotations\n"
                "Follow the existing code style in the project."
            ),
            delay_after=5.0,
        ))
        wf.add_step(WorkflowStep(
            name="4. Build UI Screens",
            prompt=(
                "Build the UI screens for '{feature_name}' in lib/screens/. "
                "Create beautiful, responsive Flutter widgets following Material 3 design. "
                "Use the existing theme and design patterns from the project. "
                "Include proper error states, loading indicators, and empty states."
            ),
            delay_after=5.0,
        ))
        wf.add_step(WorkflowStep(
            name="5. Add State Management",
            prompt=(
                "Create the state management for '{feature_name}'. "
                "Add Provider/ChangeNotifier classes in lib/providers/. "
                "Connect the UI screens to the providers. "
                "Handle loading states, error states, and data caching. "
                "Follow the existing provider patterns in the project."
            ),
            delay_after=5.0,
        ))
        wf.add_step(WorkflowStep(
            name="6. Write Tests",
            prompt=(
                "Write comprehensive tests for the '{feature_name}' feature:\n"
                "- Unit tests for models and providers\n"
                "- Widget tests for UI components\n"
                "Put tests in the test/ directory mirroring the lib/ structure. "
                "Aim for good coverage of edge cases."
            ),
            delay_after=3.0,
        ))
        wf.add_step(WorkflowStep(
            name="7. Integration Check",
            prompt=(
                "Review all the code created for '{feature_name}'. "
                "Check for:\n"
                "- Missing imports\n"
                "- Navigation routes registered\n"
                "- Provider registered in main.dart\n"
                "- No compile errors\n"
                "Fix any issues found and confirm the feature is fully integrated."
            ),
            delay_after=2.0,
        ))
        workflows["Full Feature Dev"] = wf

        # === Bug Fix & Test ===
        wf2 = Workflow(
            name="Bug Fix & Test",
            description="Diagnose a bug, fix it, write a regression test, and verify"
        )
        wf2.add_step(WorkflowStep(
            name="1. Diagnose Bug",
            prompt=(
                "There is a bug in the project at {project_path}: '{bug_description}'. "
                "Investigate the issue by:\n"
                "- Reading the relevant source files\n"
                "- Tracing the data flow\n"
                "- Identifying the root cause\n"
                "Explain what's happening and why."
            ),
            delay_after=5.0,
        ))
        wf2.add_step(WorkflowStep(
            name="2. Implement Fix",
            prompt=(
                "Fix the bug identified in the previous step. "
                "Make the minimal necessary changes. "
                "Explain each change you make and why it fixes the issue."
            ),
            delay_after=5.0,
        ))
        wf2.add_step(WorkflowStep(
            name="3. Write Regression Test",
            prompt=(
                "Write a regression test that would catch this bug if it reappears. "
                "The test should:\n"
                "- Reproduce the exact scenario that triggered the bug\n"
                "- Verify the fix works correctly\n"
                "- Cover any related edge cases"
            ),
            delay_after=3.0,
        ))
        wf2.add_step(WorkflowStep(
            name="4. Verify Fix",
            prompt=(
                "Run the tests and verify the bug fix is working. "
                "Also check that no other tests broke. "
                "Summarize the fix, the test results, and any remaining concerns."
            ),
            delay_after=2.0,
        ))
        workflows["Bug Fix & Test"] = wf2

        # === Code Review & Refactor ===
        wf3 = Workflow(
            name="Code Review & Refactor",
            description="Deep code review, identify improvements, refactor, and verify"
        )
        wf3.add_step(WorkflowStep(
            name="1. Deep Code Review",
            prompt=(
                "Perform a thorough code review of {file_path} in the project at {project_path}. "
                "Analyze:\n"
                "- Code quality and readability\n"
                "- Performance issues\n"
                "- Security concerns\n"
                "- Design pattern violations\n"
                "- Missing error handling\n"
                "Rate each issue by severity (Critical/High/Medium/Low)."
            ),
            delay_after=5.0,
        ))
        wf3.add_step(WorkflowStep(
            name="2. Refactor Code",
            prompt=(
                "Refactor the code based on the review findings. "
                "Priority order: Critical → High → Medium. "
                "Apply clean code principles, improve naming, extract methods, "
                "add proper error handling, and optimize performance. "
                "Keep the public API stable."
            ),
            delay_after=5.0,
        ))
        wf3.add_step(WorkflowStep(
            name="3. Add Documentation",
            prompt=(
                "Add comprehensive documentation to the refactored code:\n"
                "- Class-level dartdoc comments\n"
                "- Method documentation with @param and @return\n"
                "- Inline comments for complex logic\n"
                "- Update any existing README if needed"
            ),
            delay_after=3.0,
        ))
        wf3.add_step(WorkflowStep(
            name="4. Verify Refactoring",
            prompt=(
                "Verify the refactoring didn't break anything:\n"
                "- Run all existing tests\n"
                "- Check for compile errors\n"
                "- Ensure public API hasn't changed unexpectedly\n"
                "Provide a summary of improvements made with before/after comparison."
            ),
            delay_after=2.0,
        ))
        workflows["Code Review & Refactor"] = wf3

        # === Analyze, Fix & Sync ===
        wf4 = Workflow(
            name="Analyze, Fix & Sync",
            description="Deep project maintenance: analyze → organize → GitHub sync"
        )
        wf4.add_step(WorkflowStep(
            name="1. Analyze Needs",
            prompt=(
                "Deeply analyze the project at {project_path} and identify fixes needed. "
                "Tasks:\n"
                "- Run and review 'flutter analyze' results for errors/warnings.\n"
                "- Review 'git status' and 'git diff' for uncommitted or dirty code.\n"
                "- Identify files that are too large or logically misplaced.\n"
                "Provide a summary of what needs to be fixed and a plan for organization."
            ),
            delay_after=5.0,
        ))
        wf4.add_step(WorkflowStep(
            name="2. Organize & Fix",
            prompt=(
                "Execute the maintenance plan for {project_path}:\n"
                "- Fix the syntax errors and linting warnings identified in analysis.\n"
                "- Organize the 'lib/' structure: group related widgets, providers, and models into sub-directories.\n"
                "- Ensure all files have proper exports and matching naming conventions (lowercase_with_underscores).\n"
                "Refactor code for better readability and structure."
            ),
            delay_after=10.0,
        ))
        wf4.add_step(WorkflowStep(
            name="3. Sync to GitHub",
            prompt=(
                "Finalize the maintenance cycle and sync to GitHub.\n"
                "Tasks:\n"
                "- Run a final 'flutter analyze' to ensure no new errors were introduced.\n"
                "- Commit all changes locally with a professional, detailed message (e.g., 'refactor: organize lib structure and fix linting errors').\n"
                "- Push the changes to the origin branch.\n"
                "Confirm when the sync is complete."
            ),
            delay_after=5.0,
        ))
        workflows["Analyze, Fix & Sync"] = wf4

        # === Autonomous Feature Architect ===
        wf5 = Workflow(
            name="Autonomous Feature Architect",
            description="End-to-end full-stack development: discovery → implementation → test → deploy"
        )
        wf5.add_step(WorkflowStep(
            name="1. Audit & Blueprint",
            prompt=(
                "You are the Lead Mobile Architect for 'MyCircle', a premium media app.\n"
                "Analyze {project_path} and identify the next high-value feature or critical refactor needed.\n"
                "Constraints:\n"
                "- Architecture: MVVM with Provider for state management.\n"
                "- Backend: Supabase (Auth, Database, Storage).\n"
                "- UI Style: Premium Glassmorphism (Flutter Acrylic) & DM Sans typography.\n"
                "Output a technical blueprint including:\n"
                "- New models/entities needed (mapped to Supabase tables).\n"
                "- Logic layers (Providers/Repositories).\n"
                "- UI screen designs and widget breakdown.\n"
                "- Provide a clear execution plan."
            ),
            delay_after=5.0,
        ))
        wf5.add_step(WorkflowStep(
            name="2. Core Logic Implementation",
            prompt=(
                "Implement the logic layer for the blueprint in {project_path}.\n"
                "Think step-by-step about the state flow:\n"
                "1. Create Data Models & DTOs (ensure `fromJson`/`toJson` for Supabase).\n"
                "2. Implement Repositories/Services (isolate Supabase calls here).\n"
                "3. Implement Providers (`ChangeNotifier`) to manage state and expose getters.\n"
                "Rules:\n"
                "- Use the `AntigravityProvider` pattern.\n"
                "- Handle loading states (`_isLoading`) and error handling gracefully.\n"
                "- Ensure strict type safety."
            ),
            delay_after=10.0,
        ))
        wf5.add_step(WorkflowStep(
            name="3. Premium UI Development",
            prompt=(
                "Build the UI for the new feature in {project_path}.\n"
                "Aesthetics: 'Ultimate Home Screen' quality.\n"
                "- Use `flutter_acrylic` for window effects (if desktop).\n"
                "- Use `Chewie` if video playback is involved.\n"
                "- Implement smooth animations and glassmorphism gradients.\n"
                "- Use `Consumer<Provider>` to reactively rebuild widgets.\n"
                "Focus on a premium, wow-factor user experience."
            ),
            delay_after=10.0,
        ))
        wf5.add_step(WorkflowStep(
            name="4. Verification & Testing",
            prompt=(
                "Secure the feature in {project_path} with tests.\n"
                "- Write unit tests for the new Providers and Repositories (mock Supabase calls).\n"
                "- Write widget tests for critical UI components (pumpWidget, verify finders).\n"
                "- Run 'flutter test' to ensure everything passes.\n"
                "Verify high code coverage for the new module."
            ),
            delay_after=10.0,
        ))
        wf5.add_step(WorkflowStep(
            name="5. Polish & Performance",
            prompt=(
                "Final cleanup for {project_path}.\n"
                "- Run 'flutter analyze' and fix ALL linting issues.\n"
                "- Optimize performance: use `const` constructors, `RepaintBoundary` for complex animations.\n"
                "- Ensure all public members are documented.\n"
                "- Check for memory leaks (disposed controllers).\n"
                "Make the code production-ready."
            ),
            delay_after=5.0,
        ))
        wf5.add_step(WorkflowStep(
            name="6. Sync & Ship",
            prompt=(
                "Commit and push the new feature for {project_path}.\n"
                "- Create a detailed commit message describing the architecture and features added.\n"
                "- Push the changes to GitHub.\n"
                "Provide a final summary of the new feature."
            ),
            delay_after=5.0,
        ))
        workflows["Autonomous Feature Architect"] = wf5

        # === The Executive Developer ===
        wf6 = Workflow(
            name="The Executive Developer",
            description="High-level project management: Logic → UI → Git → Build"
        )
        wf6.add_step(WorkflowStep(
            name="1. Executive Audit & Organize",
            prompt=(
                "Persona: Senior Executive Developer.\n"
                "Goal: Audit {project_path} and optimize everything.\n"
                "Tasks to consider:\n"
                "1. GIT: Analyze commit history, plan meaningful COMMITS, update README, and generate a CHANGELOG.\n"
                "2. ORGANIZE: Identify misplaced files, redundant logic, and refactor for a clean structure.\n"
                "3. UI ENHANCE: Brainstorm and implement premium UI improvements (Glassmorphism, animations).\n"
                "4. BETTER: Think deeply about what can be better in the current codebase.\n"
                "5. BUILD: Ensure the project builds and runs perfectly.\n\n"
                "Plan the first phase of organization and Git cleanup now."
            ),
            delay_after=10.0,
        ))
        wf6.add_step(WorkflowStep(
            name="2. Refactor & UI Polish",
            prompt=(
                "Execute the 'ORGANIZE' and 'UI ENHANCE' plans for {project_path}.\n"
                "Move files to proper domains, fix naming, and apply the premium visual styles.\n"
                "Ensure state management (Provider) is used correctly throughout."
            ),
            delay_after=20.0,
        ))
        wf6.add_step(WorkflowStep(
            name="3. Git Excellence & Sync",
            prompt=(
                "Finalize the cycle for {project_path}:\n"
                "- Write/Update README and CHANGELOG.\n"
                "- Categorize and ORGANIZE COMMITS for clarity.\n"
                "- Perform final PUSH to origin.\n"
                "- Confirm BUILD and RUN status."
            ),
            delay_after=10.0,
        ))
        workflows["The Executive Developer"] = wf6

        # === Enterprise Solution Architect ===
        wf7 = Workflow(
            name="Enterprise Solution Architect",
            description="High-governance architecture, security, and stability enforcement"
        )
        
        # Define the base enterprise instruction
        ent_base = (
            "You are acting as:\n"
            "- Enterprise Software Architect\n"
            "- Flutter Desktop Technical Lead\n"
            "- Backend Security Auditor\n"
            "- DevOps Governance Reviewer\n\n"
            "This is an ENTERPRISE application. Enforce scalability, security, auditability, and maintainability.\n"
            "Reject shortcuts. Reject temporary hacks. Reject architectural violations. Follow sections strictly."
        )

        wf7.add_step(WorkflowStep(
            name="1. Enterprise Audit & Scorecard",
            prompt=(
                f"{ent_base}\n\n"
                "=========================================================\n"
                "STEP 1: ARCHITECTURE, SECURITY & EXTERNAL AUDIT\n"
                "=========================================================\n"
                "Analyze {project_path} focusing on:\n"
                "1️⃣ ENTERPRISE ARCHITECTURE GOVERNANCE (Clean Architecture, DI, Layer constraints)\n"
                "3️⃣ ENTERPRISE SECURITY – SUPABASE (RLS, keys, auth guards, pagination)\n"
                "4️⃣ DEPENDENCY & SUPPLY CHAIN CONTROL (pubspec analysis, linting)\n"
                "🔟 FINAL ENTERPRISE SCORECARD (Score 0–100 for current state)\n\n"
                "Output: Detailed Audit report, Scorecard, and list of ARCHITECTURAL BREACHES / SECURITY RISKS."
            ),
            delay_after=10.0,
        ))

        wf7.add_step(WorkflowStep(
            name="2. Governed Implementation & Quality",
            prompt=(
                f"{ent_base}\n\n"
                "=========================================================\n"
                "STEP 2: IMPLEMENTATION & CODE QUALITY ENFORCEMENT\n"
                "=========================================================\n"
                "Identify and implement the next high-value feature/refactor for {project_path}.\n"
                "Enforce:\n"
                "6️⃣ CODE QUALITY (Large widgets, setState misuse, leaks, async handling)\n"
                "7️⃣ PERFORMANCE & SCALABILITY (Caching, lazy loading, API efficiency)\n"
                "Apply the 'refactor blueprint' identified in Audit step. Ensure zero lint warnings."
            ),
            delay_after=20.0,
        ))

        wf7.add_step(WorkflowStep(
            name="3. Stability & Hardening",
            prompt=(
                f"{ent_base}\n\n"
                "=========================================================\n"
                "STEP 3: WINDOWS STABILITY & SECURITY MITIGATION\n"
                "=========================================================\n"
                "Verify and harden {project_path}:\n"
                "2️⃣ WINDOWS ENTERPRISE STABILITY (Reproducible build, disposables, UI thread blocking)\n"
                "9️⃣ TESTING ENTERPRISE STANDARD (Unit/Widget tests, CI readiness, coverage estimate)\n"
                "Execute the security mitigation plan for any HIGH/CRITICAL risks identified."
            ),
            delay_after=15.0,
        ))

        wf7.add_step(WorkflowStep(
            name="4. Documentation & Git Registry",
            prompt=(
                f"{ent_base}\n\n"
                "=========================================================\n"
                "STEP 4: GIT GOVERNANCE & DOCUMENTATION\n"
                "=========================================================\n"
                "Finalize the release for {project_path}:\n"
                "5️⃣ ENTERPRISE GIT GOVERNANCE (Atomic commits, branch naming, atomic structure)\n"
                "8️⃣ DOCUMENTATION GOVERNANCE (README overview, setup, CHANGELOG semver)\n"
                "Generate improved commit messages and finalize all governance registry files."
            ),
            delay_after=10.0,
        ))
        
        workflows["Enterprise Solution Architect"] = wf7

        return workflows

    def save_workflow(self, workflow: Workflow, save_dir: str) -> str:
        """Save a workflow to a JSON file"""
        os.makedirs(save_dir, exist_ok=True)
        safe_name = workflow.name.lower().replace(" ", "_").replace("/", "_")
        filepath = os.path.join(save_dir, f"workflow_{safe_name}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(workflow.to_dict(), f, indent=2, ensure_ascii=False)
        return filepath

    def load_workflow(self, filepath: str) -> Workflow:
        """Load a workflow from a JSON file"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Workflow.from_dict(data)

    def load_all_saved(self, save_dir: str) -> Dict[str, Workflow]:
        """Load all saved workflows from a directory"""
        workflows = {}
        if not os.path.isdir(save_dir):
            return workflows
        for fname in os.listdir(save_dir):
            if fname.endswith(".json") and fname.startswith("workflow_"):
                try:
                    full_path = os.path.join(save_dir, fname)
                    wf = self.load_workflow(full_path)
                    wf.filepath = full_path
                    workflows[wf.name] = wf
                except Exception as e:
                    logger.warning(f"Failed to load workflow {fname}: {e}")
        return workflows


if __name__ == "__main__":
    # Quick self-test
    engine = WorkflowEngine()
    print(f"✅ WorkflowEngine loaded with {len(engine.builtin_workflows)} built-in workflows:")
    for name, wf in engine.builtin_workflows.items():
        print(f"   • {name} — {len(wf.steps)} steps — {wf.description}")
