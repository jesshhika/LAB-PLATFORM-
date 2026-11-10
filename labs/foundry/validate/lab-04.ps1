$ErrorActionPreference = 'Stop'
$checks = @()
$workspace = 'C:\Labs\lab4'
$toolFile = Join-Path $workspace 'tool-config.json'
$testFile = Join-Path $workspace 'tool-test.txt'
function Add-Check($Name, $Passed, $Message) {
  $script:checks += [pscustomobject]@{ name = $Name; passed = [bool]$Passed; message = $Message }
}
Add-Check 'workspace' (Test-Path $workspace) "$workspace exists."
Add-Check 'tool-config' (Test-Path $toolFile) "$toolFile exists."
Add-Check 'safe-tool-test' (Test-Path $testFile) "$testFile records a non-destructive tool result."
[pscustomobject]@{ passed = @($checks | Where-Object { -not $_.passed }).Count -eq 0; checks = $checks } |
  ConvertTo-Json -Depth 5 -Compress
