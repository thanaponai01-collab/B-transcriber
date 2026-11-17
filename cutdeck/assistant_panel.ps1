# Reads Premiere's AI Assistant panel through Windows UI Automation, and optionally sends a
# prompt first. Prints a JSON array of the panel's elements in tree order (depth-first), each with its depth.
# Proven live: docs/PREMIERE_FACTS.md, "Driving the AI Assistant (beta) chat".
# Exit 2: Premiere is not running. Exit 3: the assistant panel is closed. Exit 4: cannot send.
param([string]$PromptBase64 = "")
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$Scope = [System.Windows.Automation.TreeScope]
$Type = [System.Windows.Automation.ControlType]

$windows = @(Get-Process "Adobe Premiere Pro*" -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 })
if (-not $windows) { [Console]::Error.WriteLine("Premiere is not running"); exit 2 }
$isPanel = New-Object System.Windows.Automation.PropertyCondition($A::AutomationIdProperty, "RootWebArea")
$doc = $null
foreach ($window in $windows) {
    $doc = $A::FromHandle($window.MainWindowHandle).FindFirst($Scope::Descendants, $isPanel)
    if ($doc) { break }
}
if (-not $doc) { [Console]::Error.WriteLine("The AI Assistant panel is closed"); exit 3 }

function Find($type, $name) {
    $doc.FindFirst($Scope::Descendants, (New-Object System.Windows.Automation.AndCondition(
        (New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, $type)),
        (New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, $name)))))
}

if ($PromptBase64) {
    $prompt = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($PromptBase64))
    $box = Find $Type::Edit "Describe what you want to do"
    $send = Find $Type::Button "Send"
    if (-not $box -or -not $send) { [Console]::Error.WriteLine("Chat box or Send button not found"); exit 4 }
    $box.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($prompt)
    Start-Sleep -Milliseconds 600
    if (-not $send.Current.IsEnabled) { [Console]::Error.WriteLine("Send stayed disabled; the assistant may be busy"); exit 4 }
    $send.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    Start-Sleep -Milliseconds 1500
}

$walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
$elements = New-Object System.Collections.Generic.List[object]
function Walk($element, $depth) {
    $child = $walker.GetFirstChild($element)
    $current = $element.Current
    $elements.Add([ordered]@{
        type = ($current.ControlType.ProgrammaticName -replace "ControlType\.", "")
        name = $current.Name; depth = $depth; leaf = ($null -eq $child) })
    while ($null -ne $child) { Walk $child ($depth + 1); $child = $walker.GetNextSibling($child) }
}
Walk $doc 0
ConvertTo-Json -InputObject $elements.ToArray() -Compress
