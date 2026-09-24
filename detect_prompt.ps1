Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$windowTitle = "Codex"
$targetText = "Do you want me to refresh"

# Find the window
$automation = [Windows.Automation.AutomationElement]::RootElement
$condition = New-Object Windows.Automation.PropertyCondition([Windows.Automation.AutomationElement]::NameProperty, $windowTitle)
$window = $automation.FindFirst([Windows.Automation.TreeScope]::Children, $condition)

if ($null -eq $window) {
    Write-Host "Window '$windowTitle' not found."
    exit 1
}

# Find all elements within the window
$elements = $window.FindAll([Windows.Automation.TreeScope]::Descendants, [Windows.Automation.Condition]::TrueCondition)

Write-Host "Searching for '$targetText' in $($elements.Count) elements..."

$found = $false
foreach ($el in $elements) {
    if ($el.Current.Name -like "*$targetText*") {
        Write-Host "FOUND: $($el.Current.Name)"
        $found = $true
        break
    }
}

if (-not $found) {
    Write-Host "Text '$targetText' not found."
}
