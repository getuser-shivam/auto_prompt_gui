Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$windowTitle = "Codex"

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

Write-Host "Inspecting $($elements.Count) elements in '$windowTitle'..."

foreach ($el in $elements) {
    try {
        $name = $el.Current.Name
        $class = $el.Current.ClassName
        $type = $el.Current.ControlType.ProgrammaticName
        
        if ($name -or $class) {
            Write-Host "Type: $type | Class: $class | Name: $name"
        }
    } catch {}
}
