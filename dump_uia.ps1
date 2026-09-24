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

Write-Host "Total elements: $($elements.Count)"

for ($i=0; $i -lt $elements.Count; $i++) {
    $el = $elements[$i]
    try {
        $type = $el.Current.ControlType.ProgrammaticName
        $name = $el.Current.Name
        $id = $el.Current.AutomationId
        $class = $el.Current.ClassName
        Write-Host "[$i] Type: $type | Name: '$name' | Id: '$id' | Class: '$class'"
    } catch {
        Write-Host "[$i] Error accessing element"
    }
}
