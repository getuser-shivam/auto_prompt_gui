#!/usr/bin/env python3
"""
AI Chatbot Module for Auto-Prompt Workflow GUI
Provides AI-powered chat using Pollinations.ai (No-Cost, No-Signup).
Can help generate, refine, and explain workflow prompts.
"""

import os
import json
import threading
import requests
from pathlib import Path
from typing import Optional, List, Dict, Callable
import logging

logger = logging.getLogger(__name__)


class AIChatbot:
    """AI Chatbot with multiple provider support (Pollinations, Groq, etc.)"""

    SYSTEM_PROMPT = """You are an AI assistant embedded in an Auto-Prompt Workflow Runner.
You help users create, refine, and optimize prompts for AI coding editors (Antigravity/Gemini, Windsurf, Cursor).
When the user asks to 'Generate Workflow', output a JSON list of prompts.
Format: ["Prompt 1", "Prompt 2", ...]
When generating workflow steps, number them and keep each prompt focused on one task."""

    PROVIDERS = ["Pollinations (No Signup)", "Groq (Fast/Key Required)"]
    MODELS = {
        "Pollinations (No Signup)": ["openai", "mistral", "p1", "unity"],
        "Groq (Fast/Key Required)": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "llama3-70b-8192",
            "mixtral-8x7b-32768",
            "gemma2-9b-it"
        ]
    }

    def __init__(self, api_key: str = "", provider: str = "Pollinations (No Signup)", model: str = ""):
        self._api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self._provider = provider
        self._model_name = model or self.MODELS[provider][0]
        self._chat_history: List[Dict[str, str]] = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        self._is_ready = True
        self.on_response: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_status: Optional[Callable[[str], None]] = None
        self._project_context: str = ""

    def _initialize(self):
        self._is_ready = True

    def set_api_key(self, key: str):
        self._api_key = key.strip()
        if "Groq" in self._provider:
            os.environ["GROQ_API_KEY"] = self._api_key
        else:
            os.environ["POLLINATIONS_API_KEY"] = self._api_key
        return True

    def set_provider(self, provider: str):
        if provider in self.PROVIDERS:
            self._provider = provider
            # Default to first model for this provider
            self._model_name = self.MODELS[provider][0]
            return True
        return False

    def set_model(self, model_name: str):
        if model_name in self.MODELS.get(self._provider, []):
            self._model_name = model_name
            return True
        return False

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def is_ready(self) -> bool:
        return self._is_ready

    @property
    def status_text(self) -> str:
        icon = "🟢" if self._is_ready else "🔴"
        return f"{icon} {self._provider}"

    def send_message(self, message: str, context: str = "", callback: Callable[[str], None] = None, trigger_on_response: bool = True):
        """Send a message to the chatbot (async — runs in background thread)"""
        thread = threading.Thread(
            target=self._send_message_sync,
            args=(message, context, callback, trigger_on_response),
            daemon=True
        )
        thread.start()

    def _send_message_sync(self, message: str, context: str = "", callback: Callable[[str], None] = None, trigger_on_response: bool = True):
        """Synchronous message send (called from background thread)"""
        try:
            if self.on_status:
                self.on_status("🤔 Thinking...")

            full_message = message
            if context:
                full_message = f"[Current workflow context:\n{context}]\n\nUser: {message}"

            # Prepare messages for API
            current_messages = self._chat_history.copy()
            current_messages.append({"role": "user", "content": full_message})

            reply = ""
            last_err = None
            
            # Simple retry loop
            for attempt in range(3):
                try:
                    if "Groq" in self._provider:
                        url = "https://api.groq.com/openai/v1/chat/completions"
                        headers = {
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json"
                        }
                        payload = {
                            "messages": current_messages,
                            "model": self._model_name,
                            "temperature": 0.7
                        }
                        response = requests.post(url, json=payload, headers=headers, timeout=60)
                        if response.status_code == 200:
                            reply = response.json()["choices"][0]["message"]["content"]
                            break
                        else:
                            last_err = f"Groq API Error ({response.status_code}): {response.text}"
                    else:
                        # Pollinations
                        url = "https://text.pollinations.ai/"
                        payload = {
                            "messages": current_messages,
                            "model": self._model_name,
                            "jsonMode": False
                        }
                        headers = {"Content-Type": "application/json"}
                        response = requests.post(url, json=payload, headers=headers, timeout=60)
                        if response.status_code == 200:
                            reply = response.text
                            break
                        else:
                            last_err = f"Pollinations API Error ({response.status_code}): {response.text}"
                
                except requests.exceptions.RequestException as e:
                    last_err = f"Network/Timeout Error: {str(e)}"
                
                if self.on_status:
                    self.on_status(f"🤔 Retrying ({attempt+1}/3)...")
            
            if not reply:
                raise RuntimeError(last_err or "Max retries reached")

            # Update history
            self._chat_history.append({"role": "user", "content": message})
            self._chat_history.append({"role": "assistant", "content": reply})

            if trigger_on_response and self.on_response:
                self.on_response(reply)
            
            if callback:
                callback(reply)

            if self.on_status:
                self.on_status("Ready")

        except Exception as e:
            logger.error(f"Chatbot error: {e}")
            if self.on_error:
                self.on_error(f"Error: {str(e)}")
            if self.on_status:
                self.on_status("❌ Error")

    def send_message_blocking(self, message: str, context: str = "") -> str:
        """Synchronous, blocking message send. Returns the reply text or raises an exception."""
        try:
            if self.on_status:
                self.on_status("🤔 Thinking...")

            full_message = message
            if context:
                full_message = f"[Current workflow context:\n{context}]\n\nUser: {message}"

            current_messages = self._chat_history.copy()
            current_messages.append({"role": "user", "content": full_message})

            reply = ""
            last_err = None
            for attempt in range(3):
                try:
                    if "Groq" in self._provider:
                        url = "https://api.groq.com/openai/v1/chat/completions"
                        headers = {
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json"
                        }
                        payload = {
                            "messages": current_messages,
                            "model": self._model_name,
                            "temperature": 0.7
                        }
                        response = requests.post(url, json=payload, headers=headers, timeout=60)
                        if response.status_code == 200:
                            reply = response.json()["choices"][0]["message"]["content"]
                            break
                        else:
                            last_err = f"Groq API Error ({response.status_code}): {response.text}"
                    else:
                        url = "https://text.pollinations.ai/"
                        payload = {
                            "messages": current_messages,
                            "model": self._model_name,
                            "jsonMode": False
                        }
                        headers = {"Content-Type": "application/json"}
                        response = requests.post(url, json=payload, headers=headers, timeout=60)
                        if response.status_code == 200:
                            reply = response.text
                            break
                        else:
                            last_err = f"Pollinations API Error ({response.status_code}): {response.text}"
                except requests.exceptions.RequestException as e:
                    last_err = f"Network/Timeout Error: {str(e)}"
            
            if not reply:
                raise RuntimeError(last_err or "Max retries reached")

            self._chat_history.append({"role": "user", "content": message})
            self._chat_history.append({"role": "assistant", "content": reply})

            if self.on_response:
                self.on_response(reply)
            
            return reply

        except Exception as e:
            logger.error(f"Chatbot blocking error: {e}")
            if self.on_error:
                self.on_error(f"Error: {str(e)}")
            if self.on_status:
                self.on_status("❌ Error")
            raise RuntimeError(str(e))

    def add_history(self, role: str, content: str):
        """Manually add an entry to history (e.g. for logging external editor prompts)"""
        self._chat_history.append({"role": role, "content": content})
        if self.on_response and role == "assistant":
            self.on_response(content)

    def generate_workflow_prompts(self, task_description: str, callback: Optional[Callable[[str], None]] = None) -> None:
        """Ask AI to generate a set of workflow prompts for a task"""
        context_str = f"\n\nPROJECT CONTEXT:\n{self._project_context}" if self._project_context else ""
        prompt = (
            f"Task: {task_description}{context_str}\n\n"
            "Based on the project context above (if any), generate a JSON list of workflow prompts "
            "for the next steps in continuous development.\n"
            "IMPORTANT: Output ONLY the raw JSON list, no markdown, no context. "
            "Example: [\"Step 1\", \"Step 2\", ...]"
        )
        self.send_message(prompt, callback=callback)

    def refine_prompt(self, current_prompt: str, callback: Optional[Callable[[str], None]] = None) -> None:
        """Ask AI to refine a single prompt"""
        prompt = f"Refine this prompt for better AI results: '{current_prompt}'. Return ONLY the refined prompt text."
        self.send_message(prompt, callback=callback, trigger_on_response=False)

    def clear_history(self):
        """Reset the conversation"""
        self._chat_history = [{"role": "system", "content": self.SYSTEM_PROMPT}]

    def get_history(self) -> List[Dict[str, str]]:
        return self._chat_history.copy()

    def set_project_context(self, context: str):
        """Set project-specific knowledge (e.g. README/TODO contents)"""
        self._project_context = context

    def get_project_context(self) -> str:
        return self._project_context


if __name__ == "__main__":
    # Test stub
    pass
