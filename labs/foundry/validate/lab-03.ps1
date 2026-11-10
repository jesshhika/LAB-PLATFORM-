$ErrorActionPreference = 'Stop'
$checks = @()
$workspace = 'C:\Labs\lab3'
$agentFile = Join-Path $workspace 'agent.json'
function Add-Check($Name, $Passed, $Message) {
  $script:checks += [pscustomobject]@{ name = $Name; passed = [bool]$Passed; message = $Message }
}
Add-Check 'workspace' (Test-Path $workspace) "$workspace exists."
Add-Check 'agent-config' (Test-Path $agentFile) "$agentFile exists."
$promptLog = Join-Path $workspace 'agent-test.txt'
Add-Check 'prompt-tests' ((Test-Path $promptLog) -and ((Get-Content $promptLog -Raw).Length -gt 0)) "$promptLog contains test results."
[pscustomobject]@{ passed = @($checks | Where-Object { -not $_.passed }).Count -eq 0; checks = $checks } |
  ConvertTo-Json -Depth 5 -Compress
