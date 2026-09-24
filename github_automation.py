#!/usr/bin/env python3
"""
GitHub Automation for MyCircle Project
Automated GitHub operations including issues, PRs, releases, and repository management
"""

import os
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import logging
from github import Github, GithubException
import git

logger = logging.getLogger(__name__)

class GitHubAutomation:
    """Automated GitHub operations for MyCircle project"""
    
    def __init__(self, repo_name: str = "getuser-shivam/MyCircle", github_token: str = None):
        self.repo_name = repo_name
        self.github_token = github_token or os.getenv('GITHUB_TOKEN')
        
        if not self.github_token:
            logger.warning("GitHub token not provided. Some features will be limited.")
            self.github = None
        else:
            try:
                self.github = Github(self.github_token)
                self.repo = self.github.get_repo(repo_name)
                logger.info(f"Connected to GitHub repository: {repo_name}")
            except Exception as e:
                logger.error(f"Error connecting to GitHub: {e}")
                self.github = None
                self.repo = None
    
    def create_feature_issue(self, title: str, description: str, priority: str = "medium", 
                           labels: List[str] = None, assignees: List[str] = None) -> bool:
        """Create a GitHub issue for a new feature"""
        if not self.repo:
            logger.error("GitHub repository not available")
            return False
        
        try:
            issue_body = f"""
## Description
{description}

## Priority
{priority}

## Implementation Notes
- Follow the existing code structure
- Add proper tests
- Update documentation

## Acceptance Criteria
- [ ] Feature implemented according to requirements
- [ ] Tests added and passing
- [ ] Code reviewed and approved
- [ ] Documentation updated

---
*Automatically created by MyCircle Automation Suite*
"""
            
            # Prepare labels
            if labels is None:
                labels = ["enhancement", "automation-generated"]
            if priority.lower() not in labels:
                labels.append(priority.lower())
            
            issue = self.repo.create_issue(
                title=title,
                body=issue_body,
                labels=labels,
                assignees=assignees or []
            )
            
            logger.info(f"Created GitHub issue: {issue.html_url}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating GitHub issue: {e}")
            return False
    
    def create_bug_issue(self, title: str, description: str, severity: str = "medium",
                        stack_trace: str = None, environment: str = None) -> bool:
        """Create a GitHub issue for a bug report"""
        if not self.repo:
            logger.error("GitHub repository not available")
            return False
        
        try:
            issue_body = f"""
## Bug Description
{description}

## Severity
{severity}

## Environment
{environment or 'Not specified'}

## Stack Trace
```
{stack_trace or 'No stack trace provided'}
```

## Steps to Reproduce
1. 
2. 
3. 

## Expected Behavior
*Describe what should happen*

## Actual Behavior
*Describe what actually happens*

---
*Automatically created by MyCircle Automation Suite*
"""
            
            labels = ["bug", "automation-generated", severity.lower()]
            
            issue = self.repo.create_issue(
                title=f"Bug: {title}",
                body=issue_body,
                labels=labels
            )
            
            logger.info(f"Created bug issue: {issue.html_url}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating bug issue: {e}")
            return False
    
    def create_pull_request(self, branch_name: str, title: str, description: str, 
                          base_branch: str = "main") -> bool:
        """Create a pull request for a feature branch"""
        if not self.repo:
            logger.error("GitHub repository not available")
            return False
        
        try:
            # Check if branch exists
            try:
                self.repo.get_branch(branch_name)
            except GithubException:
                logger.error(f"Branch {branch_name} does not exist")
                return False
            
            # Create pull request
            pr_body = f"""
## Description
{description}

## Changes
- 

## Testing
- 

## Checklist
- [ ] Code follows project guidelines
- [ ] Tests added and passing
- [ ] Documentation updated
- [ ] Ready for review

---
*Automatically created by MyCircle Automation Suite*
"""
            
            pr = self.repo.create_pull(
                title=title,
                body=pr_body,
                head=branch_name,
                base=base_branch
            )
            
            logger.info(f"Created pull request: {pr.html_url}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating pull request: {e}")
            return False
    
    def create_release(self, version: str, release_notes: str, prerelease: bool = False) -> bool:
        """Create a GitHub release"""
        if not self.repo:
            logger.error("GitHub repository not available")
            return False
        
        try:
            # Create release
            release = self.repo.create_git_release(
                tag=version,
                name=f"MyCircle v{version}",
                message=release_notes,
                draft=False,
                prerelease=prerelease
            )
            
            logger.info(f"Created release: {release.html_url}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating release: {e}")
            return False
    
    def get_repository_stats(self) -> Dict[str, Any]:
        """Get comprehensive repository statistics"""
        if not self.repo:
            return {"error": "GitHub repository not available"}
        
        try:
            stats = {
                "name": self.repo.name,
                "full_name": self.repo.full_name,
                "description": self.repo.description,
                "stars": self.repo.stargazers_count,
                "forks": self.repo.forks_count,
                "watchers": self.repo.watchers_count,
                "open_issues": self.repo.open_issues_count,
                "language": self.repo.language,
                "created_at": self.repo.created_at.isoformat(),
                "updated_at": self.repo.updated_at.isoformat(),
                "default_branch": self.repo.default_branch,
                "size": self.repo.size,
                "license": self.repo.license.name if self.repo.license else None
            }
            
            # Get recent commits
            commits = list(self.repo.get_commits()[:10])
            stats["recent_commits"] = [
                {
                    "sha": commit.sha[:7],
                    "message": commit.commit.message.split('\n')[0],
                    "author": commit.commit.author.name,
                    "date": commit.commit.author.date.isoformat()
                }
                for commit in commits
            ]
            
            # Get open issues
            open_issues = list(self.repo.get_issues(state='open')[:20])
            stats["recent_issues"] = [
                {
                    "number": issue.number,
                    "title": issue.title,
                    "state": issue.state,
                    "created_at": issue.created_at.isoformat(),
                    "labels": [label.name for label in issue.labels]
                }
                for issue in open_issues
            ]
            
            # Get contributors
            contributors = list(self.repo.get_contributors()[:20])
            stats["contributors"] = [
                {
                    "login": contributor.login,
                    "contributions": contributor.contributions,
                    "type": contributor.type
                }
                for contributor in contributors
            ]
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting repository stats: {e}")
            return {"error": str(e)}
    
    def automate_issue_management(self) -> Dict[str, Any]:
        """Automate issue management tasks"""
        if not self.repo:
            return {"error": "GitHub repository not available"}
        
        actions = {
            "closed_stale_issues": 0,
            "added_labels": 0,
            "created_comments": 0,
            "errors": []
        }
        
        try:
            # Get open issues
            open_issues = self.repo.get_issues(state='open')
            
            for issue in open_issues:
                try:
                    # Check for stale issues (no activity for 30 days)
                    if issue.updated_at < datetime.now() - timedelta(days=30):
                        if 'stale' not in [label.name for label in issue.labels]:
                            issue.add_to_labels('stale')
                            actions["added_labels"] += 1
                            
                            # Add comment
                            comment = """
This issue has been automatically marked as stale due to no recent activity. 
It will be closed if no further activity occurs. Thank you for your contributions.

---
*Automated by MyCircle Automation Suite*
"""
                            issue.create_comment(comment)
                            actions["created_comments"] += 1
                    
                    # Close very old stale issues (60 days)
                    elif issue.updated_at < datetime.now() - timedelta(days=60):
                        if 'stale' in [label.name for label in issue.labels]:
                            issue.create_comment("Closing due to inactivity.")
                            issue.edit(state='closed')
                            actions["closed_stale_issues"] += 1
                
                except Exception as e:
                    actions["errors"].append(f"Error processing issue #{issue.number}: {e}")
            
            logger.info(f"Issue management completed: {actions}")
            return actions
            
        except Exception as e:
            logger.error(f"Error in issue management: {e}")
            actions["errors"].append(f"General error: {e}")
            return actions
    
    def create_project_board(self, board_name: str = "MyCircle Development") -> bool:
        """Create a GitHub project board"""
        if not self.github:
            logger.error("GitHub authentication not available")
            return False
        
        try:
            # Note: This requires GitHub API v4 (GraphQL) for project boards
            # For now, we'll create a template issue that describes the board structure
            
            board_description = f"""
# {board_name} Project Board

## Columns
- **Backlog**: New features and improvements
- **To Do**: Ready for development
- **In Progress**: Currently being worked on
- **Review**: Ready for code review
- **Done**: Completed tasks

## Automation Rules
- Issues move from Backlog → To Do when assigned
- Issues move from To Do → In Progress when work begins
- Issues move from In Progress → Review when PR is created
- Issues move from Review → Done when PR is merged

## Labels
- `enhancement`: New features
- `bug`: Bug fixes
- `documentation`: Documentation updates
- `testing`: Test improvements
- `performance`: Performance optimizations
- `security`: Security improvements

---
*Project board template created by MyCircle Automation Suite*
"""
            
            self.repo.create_issue(
                title=f"Project Board: {board_name}",
                body=board_description,
                labels=["project", "automation-generated"]
            )
            
            logger.info(f"Created project board template: {board_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating project board: {e}")
            return False
    
    def setup_automated_workflows(self) -> bool:
        """Set up automated GitHub workflows"""
        try:
            project_path = Path.cwd()
            workflows_dir = project_path / '.github' / 'workflows'
            workflows_dir.mkdir(parents=True, exist_ok=True)
            
            # Create automated testing workflow
            test_workflow = """
name: Automated Testing

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test-flutter:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Setup Flutter
      uses: subosito/flutter-action@v2
      with:
        flutter-version: '3.10.0'
        
    - name: Install dependencies
      run: flutter pub get
      
    - name: Run tests
      run: flutter test
      
    - name: Analyze code
      run: flutter analyze
      
  test-backend:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Setup Node.js
      uses: actions/setup-node@v3
      with:
        node-version: '18'
        
    - name: Install dependencies
      working-directory: ./backend
      run: npm install
    
    - name: Run tests
      working-directory: ./backend
      run: npm test
"""
            
            test_workflow_file = workflows_dir / 'automated-testing.yml'
            with open(test_workflow_file, 'w') as f:
                f.write(test_workflow)
            
            # Create automation workflow
            automation_workflow = """
name: Project Automation

on:
  schedule:
    - cron: '0 0 * * *'  # Daily at midnight
  workflow_dispatch:

jobs:
  automate:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Setup Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'
        
    - name: Install dependencies
      run: |
        pip install -r automation/requirements.txt
        
    - name: Run project analysis
      run: python automation/mycircle_automation.py --action analyze
      
    - name: Generate report
      run: python automation/mycircle_automation.py --action report
      
    - name: Upload report
      uses: actions/upload-artifact@v3
      with:
        name: automation-report
        path: automation_report.md
"""
            
            automation_workflow_file = workflows_dir / 'project-automation.yml'
            with open(automation_workflow_file, 'w') as f:
                f.write(automation_workflow)
            
            logger.info("GitHub workflows setup completed")
            return True
            
        except Exception as e:
            logger.error(f"Error setting up workflows: {e}")
            return False
    
    def sync_with_local_repo(self, local_path: str = ".") -> Dict[str, Any]:
        """Synchronize local repository with GitHub"""
        try:
            local_path = Path(local_path)
            if not (local_path / '.git').exists():
                return {"error": "Not a git repository"}
            
            repo = git.Repo(local_path)
            
            sync_info = {
                "current_branch": repo.active_branch.name,
                "remote_url": "",
                "ahead_commits": 0,
                "behind_commits": 0,
                "uncommitted_changes": len(repo.index.diff(None)) > 0,
                "actions": []
            }
            
            # Get remote URL
            try:
                remote_url = repo.remotes.origin.url
                sync_info["remote_url"] = remote_url
            except:
                sync_info["actions"].append("No remote origin found")
            
            # Check sync status
            try:
                origin = repo.remotes.origin
                fetch_info = origin.fetch()
                
                for info in fetch_info:
                    if info.flags & info.NEW_HEAD:
                        sync_info["behind_commits"] += info.commit.count()
                
                # Check ahead commits
                sync_info["ahead_commits"] = len(list(repo.iter_commits(f'origin/{repo.active_branch}..{repo.active_branch}')))
                
            except Exception as e:
                sync_info["actions"].append(f"Error checking sync status: {e}")
            
            return sync_info
            
        except Exception as e:
            logger.error(f"Error syncing with local repo: {e}")
            return {"error": str(e)}

def main():
    """Main function for GitHub automation CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(description='GitHub Automation for MyCircle')
    parser.add_argument('--repo', '-r', default='getuser-shivam/MyCircle', help='Repository name')
    parser.add_argument('--token', '-t', help='GitHub token')
    parser.add_argument('--action', '-a', 
                       choices=['issue', 'bug', 'pr', 'release', 'stats', 'manage', 'board', 'workflows', 'sync'],
                       default='stats', help='Action to perform')
    parser.add_argument('--title', help='Issue/PR title')
    parser.add_argument('--description', '-d', help='Issue/PR description')
    parser.add_argument('--priority', '-p', choices=['low', 'medium', 'high'], default='medium')
    parser.add_argument('--branch', '-b', help='Branch name for PR')
    parser.add_argument('--version', '-v', help='Release version')
    parser.add_argument('--local-path', '-l', default='.', help='Local repository path')
    
    args = parser.parse_args()
    
    github_automation = GitHubAutomation(args.repo, args.token)
    
    if args.action == 'issue':
        if not args.title or not args.description:
            print("Error: --title and --description required for issue creation")
            return
        
        success = github_automation.create_feature_issue(
            args.title, args.description, args.priority
        )
        print(f"Issue creation: {'Success' if success else 'Failed'}")
    
    elif args.action == 'bug':
        if not args.title or not args.description:
            print("Error: --title and --description required for bug report")
            return
        
        success = github_automation.create_bug_issue(
            args.title, args.description, args.priority
        )
        print(f"Bug report creation: {'Success' if success else 'Failed'}")
    
    elif args.action == 'pr':
        if not args.branch or not args.title:
            print("Error: --branch and --title required for PR creation")
            return
        
        success = github_automation.create_pull_request(
            args.branch, args.title, args.description or ""
        )
        print(f"PR creation: {'Success' if success else 'Failed'}")
    
    elif args.action == 'release':
        if not args.version:
            print("Error: --version required for release")
            return
        
        success = github_automation.create_release(
            args.version, args.description or ""
        )
        print(f"Release creation: {'Success' if success else 'Failed'}")
    
    elif args.action == 'stats':
        stats = github_automation.get_repository_stats()
        print("Repository Statistics:")
        print(json.dumps(stats, indent=2))
    
    elif args.action == 'manage':
        actions = github_automation.automate_issue_management()
        print("Issue Management Actions:")
        print(json.dumps(actions, indent=2))
    
    elif args.action == 'board':
        success = github_automation.create_project_board()
        print(f"Project board creation: {'Success' if success else 'Failed'}")
    
    elif args.action == 'workflows':
        success = github_automation.setup_automated_workflows()
        print(f"Workflow setup: {'Success' if success else 'Failed'}")
    
    elif args.action == 'sync':
        sync_info = github_automation.sync_with_local_repo(args.local_path)
        print("Repository Sync Information:")
        print(json.dumps(sync_info, indent=2))

if __name__ == '__main__':
    main()
