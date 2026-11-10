$ErrorActionPreference = 'Stop'
$checks = @()
$workspace = 'C:\Labs\lab2'
function Add-Check($Name, $Passed, $Message) {
  $script:checks += [pscustomobject]@{ name = $Name; passed = [bool]$Passed; message = $Message }
}
Add-Check 'workspace' (Test-Path $workspace) "$workspace exists."
$catalogNotes = Join-Path $workspace 'model-notes.txt'
Add-Check 'model-notes' (Test-Path $catalogNotes) "$catalogNotes exists with model, capability, and limitation notes."
[pscustomobject]@{ passed = @($checks | Where-Object { -not $_.passed }).Count -eq 0; checks = $checks } |
  ConvertTo-Json -Depth 5 -Compress
