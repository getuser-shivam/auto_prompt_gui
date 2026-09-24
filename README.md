# MyCircle Automation Suite

A comprehensive Python automation suite for the MyCircle Flutter project, providing automated analysis, development, GitHub operations, and Windsurf AI integration.

## 🚀 Features

### 🤖 Project Analysis
- Comprehensive code analysis
- Dependency tracking
- Complexity scoring
- Issue detection
- Improvement suggestions

### 🎯 Feature Generation
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

## 📦 Installation

### Prerequisites
- Python 3.8 or higher
- Git
- Flutter SDK (for Flutter projects)
- Node.js (for backend projects)

### Quick Setup

1. **Navigate to automation directory**
   ```bash
   cd automation
   ```

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   # Copy and edit the environment file
   cp .env.example .env
   # Add your API keys to .env
   ```

4. **Run initial setup**
   ```bash
   python setup.py
   ```

## 🔧 Configuration

### Environment Variables
Create a `.env` file with the following variables:

```env
GITHUB_TOKEN=your_github_token_here
OPENAI_API_KEY=your_openai_api_key_here
PROJECT_PATH=c:\Users\Work\Desktop\Projects\MyCircle
AUTOMATION_LOG_LEVEL=INFO
```

### GitHub Token Setup
1. Go to GitHub Settings > Developer settings > Personal access tokens
2. Generate a new token with `repo`, `issues`, `pull_requests` scopes
3. Add the token to your `.env` file

### OpenAI API Key Setup
1. Go to OpenAI Platform > API keys
2. Generate a new API key
3. Add the key to your `.env` file

## 🎯 Usage

### Basic Automation Commands

```bash
# Run complete automation suite
python mycircle_automation.py --action all

# Analyze project only
python mycircle_automation.py --action analyze

# Generate feature ideas
python mycircle_automation.py --action features

# Run tests
python mycircle_automation.py --action test

# Organize files
python mycircle_automation.py --action organize

# Generate comprehensive report
python mycircle_automation.py --action report
```

### GitHub Automation

```bash
# Create feature issue
python github_automation.py --action issue --title "New Feature" --description "Feature description"

# Create bug report
python github_automation.py --action bug --title "Bug Title" --description "Bug description"

# Get repository statistics
python github_automation.py --action stats

# Automate issue management
python github_automation.py --action manage

# Create pull request
python github_automation.py --action pr --branch "feature-branch" --title "PR Title"

# Create release
python github_automation.py --action release --version "1.0.0" --description "Release notes"
```

### Windsurf AI Integration

```bash
# Set up Windsurf workspace
python windsurf_integration.py --action setup

# Generate code with AI
python windsurf_integration.py --action generate --prompt "Create a Flutter screen for user profile"

# Analyze existing code
python windsurf_integration.py --action analyze --file lib/main.dart

# Create feature templates
python windsurf_integration.py --action workflow --feature "AI Chat" --type screen
```

## 📊 Automation Workflows

### Daily Development Workflow
1. **Morning Analysis**: `python mycircle_automation.py --action analyze`
2. **Feature Planning**: `python mycircle_automation.py --action features`
3. **Development**: Use Windsurf AI for code generation
4. **Testing**: `python mycircle_automation.py --action test`
5. **GitHub Management**: Create issues and PRs
6. **Reporting**: `python mycircle_automation.py --action report`

### Continuous Integration
- Automated testing on every commit
- Code quality analysis
- Dependency updates
- Security scanning
- Performance monitoring

## 🛠️ Advanced Usage

### Custom Feature Templates
```python
from windsurf_integration import WindsurfIntegration

windsurf = WindsurfIntegration()
templates = windsurf.create_feature_template("AI Chat", "screen")
print(templates)
```

### Custom GitHub Workflows
```python
from github_automation import GitHubAutomation

github = GitHubAutomation()
github.create_feature_issue("Custom Feature", "Description", "high")
```

### Custom Analysis
```python
from mycircle_automation import MyCircleAutomation

automation = MyCircleAutomation()
analysis = automation.analyze_project()
print(f"Complexity: {analysis.complexity_score}")
```

## 📁 Project Structure

```
automation/
├── mycircle_automation.py    # Main automation suite
├── github_automation.py      # GitHub operations
├── windsurf_integration.py   # Windsurf AI integration
├── setup.py                  # Setup script
├── requirements.txt          # Python dependencies
├── README.md                # This file
├── .env                     # Environment variables
└── automation.log           # Automation logs
```

## 🔍 Example Outputs

### Project Analysis
```
Project Analysis Complete:
  Complexity Score: 65.2/100
  Issues Found: 3
  Suggestions: 5
```

### Feature Generation
```
Generated 5 feature ideas:
  - AI-Powered Content Recommendations (High)
  - Real-time Chat System (High)
  - Advanced Analytics Dashboard (Medium)
```

### GitHub Statistics
```json
{
  "name": "MyCircle",
  "stars": 42,
  "forks": 8,
  "open_issues": 5,
  "language": "Dart"
}
```

## 🐛 Troubleshooting

### Common Issues

1. **Python not found**
   - Install Python from python.org
   - Add Python to PATH
   - Use `python3` instead of `python`

2. **GitHub Token Issues**
   - Ensure token has proper permissions
   - Check token expiration
   - Verify token in .env file

3. **OpenAI API Issues**
   - Check API key validity
   - Verify API quota
   - Check network connectivity

4. **Path Issues**
   - Verify PROJECT_PATH in .env
   - Use absolute paths
   - Check file permissions

### Debug Mode
Enable debug logging:
```bash
export AUTOMATION_LOG_LEVEL=DEBUG
python mycircle_automation.py --action analyze
```

### Logs
Check automation logs:
```bash
tail -f automation.log
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add your improvements
4. Run the automation suite
5. Create a pull request

## 📝 License

This automation suite is part of the MyCircle project and follows the same license terms.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section
2. Review the logs
3. Create an issue in the repository
4. Check the automation report

---

*🤖 Automated development powered by MyCircle Automation Suite*

**Last Updated**: 2025-02-12
