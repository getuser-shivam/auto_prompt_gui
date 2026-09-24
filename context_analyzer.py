import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
import os.path
import logging

logger = logging.getLogger(__name__)

class ContextAnalyzer:
    """Gathers workspace context (Readme, Git log, etc.) for Autopilot mode."""
    
    def __init__(self, project_path: str | Path):
        try:
            self.project_path = Path(project_path).resolve()
        except Exception:
            self.project_path = Path.cwd().resolve()
    
    def gather_file_content(self, filename: str, max_length: int = 1500) -> Optional[str]:
        """Read a file like README.md from the root directory."""
        try:
            if not self.project_path.exists() or not self.project_path.is_dir():
                return None
            filepath = self.project_path / filename
            
            # Try finding case-insensitive matches (e.g., Readme.md, readme.md, README.md)
            if not filepath.exists():
                for f in self.project_path.iterdir():
                    if f.is_file() and f.name.lower() == filename.lower():
                        filepath = f
                        break
                        
            if filepath.exists() and filepath.is_file():
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read().strip()
                    if len(content) > max_length:
                        return content[:max_length] + f"\n... [{len(content) - max_length} more chars elided]"
                    return content
        except Exception as e:
            logger.debug(f"Could not read {filename}: {e}")
        return None

    def gather_git_log(self, n: int = 5) -> Optional[str]:
        """Fetch the most recent N git commits if the project is a git repo."""
        try:
            if not self.project_path.exists() or not self.project_path.is_dir():
                return None
            if not (self.project_path / ".git").exists():
                # Check if inside a git tree dynamically
                try:
                    subprocess.check_output(
                        ["git", "rev-parse", "--is-inside-work-tree"], 
                        cwd=str(self.project_path), stderr=subprocess.DEVNULL
                    )
                except Exception:
                    return None
                    
            log_bytes = subprocess.check_output(
                ["git", "log", f"-n{n}", "--oneline"],
                cwd=str(self.project_path),
                stderr=subprocess.DEVNULL
            )
            return log_bytes.decode("utf-8").strip()
        except Exception as e:
            logger.debug(f"Could not read git log: {e}")
            return None

    def gather_git_diff(self) -> Optional[str]:
        """Fetch current uncommitted changes summary (just file names to keep it short)."""
        try:
            if not self.project_path.exists() or not self.project_path.is_dir():
                return None
            diff_bytes = subprocess.check_output(
                ["git", "status", "--short"],
                cwd=str(self.project_path),
                stderr=subprocess.DEVNULL
            )
            val = diff_bytes.decode("utf-8").strip()
            return val if val else "Clean working directory"
        except Exception:
            return None

    def build_context_block(self) -> str:
        """Constructs a comprehensive snapshot of the project state."""
        blocks = []
        
        # 1. Readme
        readme = self.gather_file_content("README.md")
        if readme:
            blocks.append(f"--- README.md snippets ---\n{readme}\n")
            
        # 2. Todo
        todo = self.gather_file_content("TODO.md")
        if todo:
            blocks.append(f"--- TODO.md ---\n{todo}\n")
            
        # 3. Git log
        git_log = self.gather_git_log()
        if git_log:
            blocks.append(f"--- Recent Git Commits ---\n{git_log}\n")
            
        # 4. Uncommitted Status
        git_status = self.gather_git_diff()
        if git_status:
            blocks.append(f"--- Current Git Status ---\n{git_status}\n")
            
        return "\n".join(blocks)

    def enhance_prompt(self, original_prompt: str, ai_agent=None) -> str:
        """
        Enhances an existing step prompt with project context.
        If an `ai_agent` (like the AIChatbot) is provided, it can be used to re-synthesize.
        For now, we statically inject context at the top to ensure the Editor Chat (Antigravity)
        always knows the high-level state.
        """
        try:
            if not self.project_path.exists() or not self.project_path.is_dir():
                return original_prompt
        except Exception:
            return original_prompt

        context_block = self.build_context_block()
        
        if not context_block.strip():
            # No context found, return original
            return original_prompt
            
        enhanced = (
            f"<project_context>\n"
            f"{context_block}\n"
            f"</project_context>\n\n"
            f"Based on the project context above, please execute the following task:\n"
            f"{original_prompt}\n"
            f"Analyze everything and then execute the step."
        )
        return enhanced

# Example manual test
if __name__ == "__main__":
    analyzer = ContextAnalyzer(".")
    print("Testing ContextAnalyzer...\n")
    print(analyzer.build_context_block())
