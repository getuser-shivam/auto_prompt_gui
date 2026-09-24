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

Write-Host "Dumping all text-like properties for $($elements.Count) elements..."

foreach ($el in $elements) {
    try {
        $props = @{
            Name = $el.Current.Name
            Class = $el.Current.ClassName
            Type = $el.Current.ControlType.ProgrammaticName
            Id = $el.Current.AutomationId
        }
        
        # Try to get Text from patterns
        $text = ""
        try {
            $textPattern = $el.GetCurrentPattern([Windows.Automation.TextPattern]::Pattern)
            if ($textPattern) {
                $text = $textPattern.DocumentRange.GetText(-1)
            }
        } catch {}
        
        if (-not $text) {
            try {
                $valuePattern = $el.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern)
                if ($valuePattern) {
                    $text = $valuePattern.Current.Value
                }
            } catch {}
        }
        
        if ($props.Name -or $props.Id -or $text) {
            Write-Host "Type: $($props.Type) | Name: $($props.Name) | Id: $($props.Id) | Text: $text"
        }
    } catch {}
}
