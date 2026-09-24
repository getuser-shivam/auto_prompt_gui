#!/usr/bin/env python3
"""
Antigravity AI Prompts for MyCircle Automation
Create powerful prompts that work with Antigravity AI model
"""

class AntigravityPrompts:
    """Prompt templates for Antigravity AI integration"""
    
    @staticmethod
    def create_feature_generation_prompt(project_analysis):
        """Create prompt for Antigravity to generate features"""
        return f"""
You are Antigravity AI, a specialized AI for Flutter development and product strategy.

PROJECT CONTEXT:
- App Name: MyCircle (Content Sharing Platform)
- Screens: {project_analysis.get('screen_count', 12)}
- Widgets: {project_analysis.get('widget_count', 15)}
- Providers: {project_analysis.get('provider_count', 4)}
- Dependencies: {project_analysis.get('dependencies', {})}
- Complexity: {project_analysis.get('complexity_score', 65.0)}/100
- Current Issues: {project_analysis.get('issues', [])}

ANTIGRAVITY AI TASK:
Generate 5 innovative features for MyCircle that leverage Flutter's capabilities and modern mobile app trends.

REQUIREMENTS:
1. Each feature must be technically feasible with current dependencies
2. Include specific implementation details
3. Consider user experience and business value
4. Provide realistic development estimates
5. Focus on content sharing and social engagement

OUTPUT FORMAT:
For each feature, provide:
- title: [Feature Name]
- description: [Detailed description of what it does]
- priority: [High/Medium/Low]
- category: [Social/AI/Performance/Communication/etc]
- estimated_hours: [Number]
- dependencies: [List of Flutter packages needed]
- implementation_steps: [Step-by-step implementation plan]
- success_metrics: [How to measure success]

ANTIGRAVITY ENHANCEMENT:
Think beyond basic features. Consider:
- AI/ML integration possibilities
- Real-time collaboration features
- Advanced content discovery
- Monetization opportunities
- Performance optimizations
- User retention strategies

Generate the response as a valid JSON array.
"""

    @staticmethod
    def create_code_analysis_prompt(file_path, code_content):
        """Create prompt for Antigravity to analyze code"""
        return f"""
You are Antigravity AI, an expert Flutter/Dart code analyst.

CODE CONTEXT:
- File: {file_path}
- Purpose: Flutter content sharing app component

CODE TO ANALYZE:
```dart
{code_content[:2000]}
```

ANTIGRAVITY ANALYSIS TASK:
Perform comprehensive code analysis focusing on:

1. CODE QUALITY (0-100 score)
2. SECURITY VULNERABILITIES
3. PERFORMANCE ISSUES
4. BEST PRACTICES VIOLATIONS
5. IMPROVEMENT OPPORTUNITIES
6. ARCHITECTURE ASSESSMENT

SPECIFIC CHECKS:
- Error handling completeness
- Memory management
- Widget optimization
- State management patterns
- Network request handling
- User input validation
- Accessibility compliance
- Code organization

OUTPUT FORMAT:
Return JSON with:
{{
    "quality_score": 85.0,
    "security_issues": ["issue1", "issue2"],
    "performance_issues": ["perf1", "perf2"],
    "best_practices_violations": ["violation1", "violation2"],
    "improvement_opportunities": ["opportunity1", "opportunity2"],
    "architecture_assessment": "Assessment of code structure",
    "specific_recommendations": ["rec1", "rec2", "rec3"]
}}

ANTIGRAVITY ENHANCEMENT:
Provide actionable, specific recommendations that can be implemented immediately.
Focus on Flutter-specific optimizations and modern development practices.
"""

    @staticmethod
    def create_code_generation_prompt(requirement, context=""):
        """Create prompt for Antigravity to generate code"""
        return f"""
You are Antigravity AI, a Flutter code generation expert.

REQUIREMENT: {requirement}

CONTEXT: {context}

ANTIGRAVITY CODE GENERATION TASK:
Generate complete, production-ready Flutter code that follows best practices.

REQUIREMENTS:
1. Use Material 3 design system
2. Include proper error handling
3. Follow Flutter widget optimization patterns
4. Use const constructors where possible
5. Add comprehensive comments
6. Include accessibility features
7. Implement proper state management
8. Handle edge cases

CODE STRUCTURE:
- Import statements at top
- Proper widget organization
- Clean, readable code
- Error boundaries
- Loading states
- Responsive design

ANTIGRAVITY ENHANCEMENT:
Generate code that:
- Is production-ready
- Follows Flutter best practices
- Is performant and optimized
- Includes proper error handling
- Has good user experience
- Is maintainable and scalable

OUTPUT:
Provide only the complete Flutter code without explanations.
Include all necessary imports and make it immediately usable.
"""

    @staticmethod
    def create_project_optimization_prompt(analysis):
        """Create prompt for Antigravity to optimize project"""
        return f"""
You are Antigravity AI, a Flutter performance and architecture optimization expert.

PROJECT ANALYSIS:
{analysis}

ANTIGRAVITY OPTIMIZATION TASK:
Analyze the MyCircle Flutter project and provide comprehensive optimization recommendations.

OPTIMIZATION AREAS:
1. PERFORMANCE OPTIMIZATIONS
2. ARCHITECTURE IMPROVEMENTS
3. CODE REFACTORING OPPORTUNITIES
4. DEPENDENCY OPTIMIZATIONS
5. BUILD SIZE REDUCTION
6. MEMORY USAGE IMPROVEMENTS
7. NETWORK OPTIMIZATIONS

SPECIFIC FOCUS:
- Widget rebuild optimization
- State management efficiency
- Image loading and caching
- List performance
- Navigation optimization
- Bundle size reduction
- Memory leak prevention

OUTPUT FORMAT:
Return JSON with:
{{
    "performance_optimizations": [
        {{"area": "area", "issue": "description", "solution": "solution", "impact": "High/Medium/Low"}}
    ],
    "architecture_improvements": [
        {{"component": "component", "current": "current_state", "recommended": "improvement", "benefit": "benefit"}}
    ],
    "refactoring_opportunities": [
        {{"file": "file", "type": "refactor_type", "description": "description", "benefit": "benefit"}}
    ],
    "dependency_optimizations": [
        {{"dependency": "package", "issue": "problem", "recommendation": "recommendation"}}
    ],
    "build_optimizations": [
        {{"technique": "technique", "implementation": "how_to", "expected_savings": "savings"}}
    ]
}}

ANTIGRAVITY ENHANCEMENT:
Provide specific, actionable recommendations with clear implementation steps.
Focus on optimizations that provide measurable improvements.
"""

    @staticmethod
    def create_testing_strategy_prompt(analysis):
        """Create prompt for Antigravity to create testing strategy"""
        return f"""
You are Antigravity AI, a Flutter testing strategy expert.

PROJECT CONTEXT:
{analysis}

ANTIGRAVITY TESTING STRATEGY TASK:
Create comprehensive testing strategy for MyCircle Flutter app.

TESTING AREAS:
1. UNIT TESTING STRATEGY
2. INTEGRATION TESTING PLAN
3. WIDGET TESTING APPROACH
4. END-TO-END TESTING SCENARIOS
5. PERFORMANCE TESTING
6. ACCESSIBILITY TESTING
7. SECURITY TESTING CONSIDERATIONS

SPECIFIC REQUIREMENTS:
- Test coverage targets
- Test automation setup
- Mock strategies
- CI/CD integration
- Testing tools recommendations
- Test data management

OUTPUT FORMAT:
Return JSON with:
{{
    "unit_testing": {{
        "coverage_target": "percentage",
        "key_components_to_test": ["component1", "component2"],
        "testing_tools": ["tool1", "tool2"],
        "mock_strategies": ["strategy1", "strategy2"]
    }},
    "integration_testing": {{
        "test_scenarios": ["scenario1", "scenario2"],
        "api_testing": "approach",
        "database_testing": "approach"
    }},
    "widget_testing": {{
        "test_cases": ["case1", "case2"],
        "testing_framework": "framework",
        "interaction_testing": "approach"
    }},
    "e2e_testing": {{
        "user_journeys": ["journey1", "journey2"],
        "testing_tools": ["tool1", "tool2"],
        "test_environments": ["env1", "env2"]
    }},
    "performance_testing": {{
        "metrics_to_monitor": ["metric1", "metric2"],
        "testing_tools": ["tool1", "tool2"],
        "performance_benchmarks": ["benchmark1", "benchmark2"]
    }},
    "accessibility_testing": {{
        "guidelines": ["WCAG", "platform_specific"],
        "testing_tools": ["tool1", "tool2"],
        "key_areas": ["area1", "area2"]
    }}
}}

ANTIGRAVITY ENHANCEMENT:
Provide a testing strategy that is practical, comprehensive, and aligned with Flutter best practices.
Include specific test cases and implementation details.
"""

# Usage examples
if __name__ == "__main__":
    # Example: Generate feature prompt
    project_analysis = {
        "screen_count": 12,
        "widget_count": 15,
        "provider_count": 4,
        "dependencies": {"provider": "^6.0.5", "http": "^1.1.0"},
        "complexity_score": 65.0,
        "issues": ["TODO comments", "Debug prints"]
    }
    
    feature_prompt = AntigravityPrompts.create_feature_generation_prompt(project_analysis)
    print("=== ANTIGRAVITY FEATURE GENERATION PROMPT ===")
    print(feature_prompt)
    
    # Example: Generate code analysis prompt
    code_analysis_prompt = AntigravityPrompts.create_code_analysis_prompt(
        "lib/screens/home_screen.dart",
        "class HomeScreen extends StatelessWidget { ... }"
    )
    print("\n=== ANTIGRAVITY CODE ANALYSIS PROMPT ===")
    print(code_analysis_prompt)
