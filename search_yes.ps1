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

Write-Host "Searching $($elements.Count) elements for 'Yes' or '1'..."

foreach ($el in $elements) {
    try {
        $props = @{}
        $props.Name = $el.Current.Name
        $props.Type = $el.Current.ControlType.ProgrammaticName
        
        # Check LegacyIAccessible properties
        try {
            $legacy = $el.GetCurrentPattern([Windows.Automation.LegacyIAccessiblePattern]::Pattern)
            $props.LegacyName = $legacy.Current.Name
            $props.LegacyDesc = $legacy.Current.Description
        } catch {}
        
        # Search for keywords
        $combined = "$($props.Name) $($props.LegacyName) $($props.LegacyDesc)"
        if ($combined -match "Yes|1\.|refresh|Submit") {
            Write-Host "MATCH FOUND!"
            Write-Host "Type: $($props.Type)"
            Write-Host "Name: $($props.Name)"
            Write-Host "LegacyName: $($props.LegacyName)"
            Write-Host "LegacyDesc: $($props.LegacyDesc)"
            Write-Host "--------------------"
        }
    } catch {}
}
