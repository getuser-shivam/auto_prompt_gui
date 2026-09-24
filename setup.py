#!/usr/bin/env python3
"""
Setup script for MyCircle Automation Suite
Installs dependencies and configures the automation environment
"""

import os
import sys
import subprocess
import json
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def install_python_dependencies():
    """Install required Python packages"""
    logger.info("Installing Python dependencies...")
    
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt"
        ])
        logger.info("Python dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install Python dependencies: {e}")
        return False

def setup_environment():
    """Set up environment configuration"""
    logger.info("Setting up environment configuration...")
    
    env_config = {
        "GITHUB_TOKEN": "your_github_token_here",
        "OPENAI_API_KEY": "your_openai_api_key_here",
        "PROJECT_PATH": str(Path.cwd().parent),
        "AUTOMATION_LOG_LEVEL": "INFO"
    }
    
    env_file = Path(".env")
    if env_file.exists():
        logger.info(".env file already exists")
        return True
    
    try:
        with open(env_file, 'w') as f:
            f.write("# MyCircle Automation Environment Variables\n")
            f.write("# Replace the placeholder values with your actual API keys\n\n")
            for key, value in env_config.items():
                f.write(f"{key}={value}\n")
        
        logger.info("Environment configuration created")
        return True
    except Exception as e:
        logger.error(f"Failed to create environment configuration: {e}")
        return False

def create_automation_scripts():
    """Create executable automation scripts"""
    logger.info("Creating automation scripts...")
    
    scripts = {
        "run_automation": """#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mycircle_automation import main

if __name__ == '__main__':
    main()
""",
        "run_windsurf": """#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from windsurf_integration import main

if __name__ == '__main__':
    main()
""",
        "run_github": """#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from github_automation import main

if __name__ == '__main__':
    main()
"""
    }
    
    try:
        for script_name, script_content in scripts.items():
            script_path = Path(f"{script_name}.py")
            with open(script_path, 'w') as f:
                f.write(script_content)
            
            # Make script executable on Unix systems
            if os.name != 'nt':
                os.chmod(script_path, 0o755)
        
        logger.info("Automation scripts created")
        return True
    except Exception as e:
        logger.error(f"Failed to create automation scripts: {e}")
        return False

def setup_git_hooks():
    """Set up Git hooks for automation"""
    logger.info("Setting up Git hooks...")
    
    hooks_dir = Path("../.git/hooks")
    if not hooks_dir.exists():
        logger.warning("Git hooks directory not found")
        return False
    
    pre_commit_hook = """#!/bin/sh
# MyCircle Automation Pre-commit Hook
python automation/mycircle_automation.py --action organize
python automation/mycircle_automation.py --action test
"""
    
    try:
        hook_file = hooks_dir / "pre-commit"
        with open(hook_file, 'w') as f:
            f.write(pre_commit_hook)
        
        if os.name != 'nt':
            os.chmod(hook_file, 0o755)
        
        logger.info("Git hooks set up successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to set up Git hooks: {e}")
        return False

def create_documentation():
    """Create documentation files"""
    logger.info("Creating documentation...")
    
    readme_content = """# MyCircle Automation Suite

A comprehensive Python automation suite for the MyCircle Flutter project, providing automated analysis, development, GitHub operations, and Windsurf AI integration.

## Features

### 🤖 Project Analysis
- Comprehensive code analysis
- Dependency tracking
- Complexity scoring
- Issue detection
- Improvement suggestions

### 🚀 Feature Generation
- AI-powered feature ideas
- Automated feature templates
- Development time estimation
- Dependency analysis

### 📁 File Organization
- Automatic import sorting
- Temporary file cleanup
- Code formatting
- Structure optimization

### 🧪 Testing & Quality
- Automated test execution
- Code quality analysis
- Performance monitoring
- Error detection

### 🐙 GitHub Integration
- Automated issue creation
- Pull request management
- Release automation
- Repository statistics
- Project board management

### 🌊 Windsurf AI Integration
- Enhanced code generation
- Intelligent code analysis
- Automated development workflows
- AI-powered suggestions

## Installation

1. **Install Dependencies**
   ```bash
   python setup.py
   ```

2. **Configure Environment**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

3. **Set Up Git Hooks**
   ```bash
   python setup.py --hooks
   ```

## Usage

### Basic Automation
```bash
# Run complete automation suite
python mycircle_automation.py --action all

# Analyze project only
python mycircle_automation.py --action analyze

# Generate feature ideas
python mycircle_automation.py --action features

# Run tests
python mycircle_automation.py --action test

# Generate report
python mycircle_automation.py --action report
```

### GitHub Automation
```bash
# Create feature issue
python github_automation.py --action issue --title "New Feature" --description "Feature description"

# Get repository stats
python github_automation.py --action stats

# Automate issue management
python github_automation.py --action manage
```

### Windsurf Integration
```bash
# Set up Windsurf workspace
python windsurf_integration.py --action setup

# Generate code with AI
python windsurf_integration.py --action generate --prompt "Create a Flutter screen"

# Analyze code
python windsurf_integration.py --action analyze --file lib/main.dart
```

## Configuration

### Environment Variables
- `GITHUB_TOKEN`: GitHub API token for repository operations
- `OPENAI_API_KEY`: OpenAI API key for AI-powered features
- `PROJECT_PATH`: Path to your MyCircle project
- `AUTOMATION_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

### GitHub Token Setup
1. Go to GitHub Settings > Developer settings > Personal access tokens
2. Generate a new token with `repo`, `issues`, `pull_requests` scopes
3. Add the token to your `.env` file

### OpenAI API Key Setup
1. Go to OpenAI Platform > API keys
2. Generate a new API key
3. Add the key to your `.env` file

## Automation Workflows

### Daily Development Workflow
1. **Morning Analysis**: Run project analysis to identify issues
2. **Feature Planning**: Generate new feature ideas
3. **Development**: Use Windsurf AI for code generation
4. **Testing**: Automated test execution
5. **GitHub Management**: Create issues and pull requests
6. **Reporting**: Generate daily progress report

### Continuous Integration
- Automated testing on every commit
- Code quality analysis
- Dependency updates
- Security scanning
- Performance monitoring

## Advanced Usage

### Custom Feature Templates
```python
from automation.windsurf_integration import WindsurfIntegration

windsurf = WindsurfIntegration()
templates = windsurf.create_feature_template("AI Chat", "screen")
```

### Custom GitHub Workflows
```python
from automation.github_automation import GitHubAutomation

github = GitHubAutomation()
github.create_feature_issue("Custom Feature", "Description", "high")
```

### Custom Analysis
```python
from automation.mycircle_automation import MyCircleAutomation

automation = MyCircleAutomation()
analysis = automation.analyze_project()
print(f"Complexity: {analysis.complexity_score}")
```

## Troubleshooting

### Common Issues
1. **GitHub Token Issues**: Ensure token has proper permissions
2. **OpenAI API Issues**: Check API key and quota
3. **Path Issues**: Verify PROJECT_PATH is correct
4. **Dependency Issues**: Run `pip install -r requirements.txt`

### Debug Mode
Enable debug logging:
```bash
export AUTOMATION_LOG_LEVEL=DEBUG
python mycircle_automation.py --action analyze
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add your improvements
4. Run the automation suite
5. Create a pull request

## License

This automation suite is part of the MyCircle project and follows the same license terms.

---

*Automated development powered by MyCircle Automation Suite*
"""
    
    try:
        readme_path = Path("README.md")
        with open(readme_path, 'w') as f:
            f.write(readme_content)
        
        logger.info("Documentation created")
        return True
    except Exception as e:
        logger.error(f"Failed to create documentation: {e}")
        return False

def main():
    """Main setup function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='MyCircle Automation Setup')
    parser.add_argument('--deps', action='store_true', help='Install dependencies only')
    parser.add_argument('--env', action='store_true', help='Setup environment only')
    parser.add_argument('--hooks', action='store_true', help='Setup Git hooks only')
    parser.add_argument('--docs', action='store_true', help='Create documentation only')
    
    args = parser.parse_args()
    
    success = True
    
    if args.deps or not any(vars(args).values()):
        success &= install_python_dependencies()
    
    if args.env or not any(vars(args).values()):
        success &= setup_environment()
    
    if args.hooks or not any(vars(args).values()):
        success &= create_automation_scripts()
        success &= setup_git_hooks()
    
    if args.docs or not any(vars(args).values()):
        success &= create_documentation()
    
    if success:
        logger.info("✅ MyCircle Automation Suite setup completed successfully!")
        logger.info("\nNext steps:")
        logger.info("1. Edit .env file with your API keys")
        logger.info("2. Run: python mycircle_automation.py --action analyze")
        logger.info("3. Check automation_report.md for results")
    else:
        logger.error("❌ Setup completed with errors. Check the logs above.")
        sys.exit(1)

if __name__ == '__main__':
    main()
