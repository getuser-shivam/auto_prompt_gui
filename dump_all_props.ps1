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

Write-Host "Dumping ALL properties for $($elements.Count) elements in '$windowTitle'..."

foreach ($el in $elements) {
    Write-Host "--- Element ---"
    try {
        $props = $el.GetSupportedProperties()
        foreach ($p in $props) {
            try {
                $val = $el.GetCurrentPropertyValue($p)
                if ($null -ne $val -and "$val" -ne "") {
                    Write-Host "$($p.ProgrammaticName): $val"
                }
            } catch {}
        }
    } catch {
        Write-Host "Error accessing properties"
    }
}
