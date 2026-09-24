import os
import re
import subprocess
import json
from pathlib import Path
from typing import List, Dict, Any

class EnterpriseRepair:
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.lib_path = self.project_path / "lib"
        
    def run_analysis(self) -> List[Dict[str, Any]]:
        """Run flutter analyze and parse results"""
        print("🔍 Running Enterprise Analysis...")
        try:
            result = subprocess.run(
                ["flutter", "analyze", "--format=machine"],
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                shell=True
            )
            
            errors = []
            for line in result.stdout.splitlines():
                if "|" in line:
                    parts = line.split("|")
                    if len(parts) >= 4:
                        errors.append({
                            "severity": parts[0],
                            "file": parts[3],
                            "line": int(parts[4]),
                            "message": parts[2],
                            "code": parts[1]
                        })
            return errors
        except Exception as e:
            print(f"❌ Error running analysis: {e}")
            return []

    def repair_missing_imports(self, errors: List[Dict[str, Any]]):
        """Try to automatically fix missing imports"""
        print("🩹 Attempting to repair missing imports...")
        repaired_count = 0
        
        for error in errors:
            if "is not defined" in error["message"] or "Undefined name" in error["message"]:
                name = re.search(r"'(.*?)'", error["message"])
                if name:
                    symbol = name.group(1)
                    found_path = self.find_symbol_definition(symbol)
                    if found_path:
                        if self.add_import_to_file(Path(error["file"]), found_path):
                            repaired_count += 1
                            print(f"✅ Repaired {symbol} in {Path(error['file']).name}")
        
        print(f"📊 Auto-repair summary: {repaired_count} fixes applied.")

    def find_symbol_definition(self, symbol: str) -> str:
        """Search the lib folder for a file defining the symbol"""
        patterns = [
            f"class {symbol}",
            f"enum {symbol}",
            f"final {symbol}",
            f"void {symbol}",
        ]
        
        for file_path in self.lib_path.rglob("*.dart"):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                for pattern in patterns:
                    if pattern in content:
                        # Return relative path for import
                        rel_path = os.path.relpath(file_path, self.lib_path).replace("\\", "/")
                        return rel_path
        return None

    def add_import_to_file(self, file_path: Path, import_rel_path: str) -> bool:
        """Add import statement to the top of the file if not already present"""
        if not file_path.exists():
            return False
            
        import_stmt = f"import '{import_rel_path}';"
        # For simplicity, if it's a provider or widget, try to guess the package structure
        # In this project, most internal imports are relative
        
        # Determine depth to calculate relative import
        # (Actually, let's just use package-style or simple relative if possible)
        # For this demo, let's try to find if it should be 'providers/...' or '../../providers/...'
        
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        if any(import_stmt in line for line in lines):
            return False # Already imported
            
        # Insert at the top, after other imports or at the very beginning
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("import '"):
                insert_idx = i + 1
        
        lines.insert(insert_idx, import_stmt + "\n")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        return True

    def generate_repair_report(self, errors: List[Dict[str, Any]]):
        """Generate a detailed report of remaining issues"""
        report_path = self.project_path / ".windsurf" / "repair_report.md"
        report_path.parent.mkdir(exist_ok=True)
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("# Enterprise Repair Report\n\n")
            f.write(f"Generated: {subprocess.check_output(['date', '/t'], shell=True).decode().strip()}\n\n")
            
            if not errors:
                f.write("🎉 **Zero issues detected!** All systems operational.\n")
            else:
                f.write(f"⚠️ **{len(errors)} issues remaining.**\n\n")
                
                f.write("## Detailed Issue Breakdown\n\n")
                for i, err in enumerate(errors):
                    f.write(f"### {i+1}. {err['severity'].upper()}: {err['message']}\n")
                    f.write(f"- **File**: `{err['file']}` (Line {err['line']})\n")
                    f.write(f"- **Code**: `{err['code']}`\n")
                    f.write(f"- **Suggested Action**: ")
                    if "import" in err['message'].lower():
                        f.write("Ensure the correct package or file is imported.\n")
                    elif "method" in err['message'].lower():
                        f.write("Check the method signature in the provider or model.\n")
                    else:
                        f.write("Review the syntax and ensure all dependencies are met.\n")
                    f.write("\n")
        
        print(f"📄 Full repair report generated at: {report_path}")

if __name__ == "__main__":
    project_root = r"c:\Users\Work\Desktop\Projects\MyCircle"
    repairer = EnterpriseRepair(project_root)
    
    errors = repairer.run_analysis()
    if errors:
        repairer.repair_missing_imports(errors)
        # Re-run after repair
        errors = repairer.run_analysis()
        repairer.generate_repair_report(errors)
    else:
        print("✅ No errors found to repair!")
