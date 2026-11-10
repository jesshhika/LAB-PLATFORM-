$ErrorActionPreference = 'Stop'
$checks = @()
$workspace = 'C:\Labs\lab5'
$evaluationFile = Join-Path $workspace 'evaluation.json'
$resultsFile = Join-Path $workspace 'results.txt'
$improvementFile = Join-Path $workspace 'improvement.txt'
function Add-Check($Name, $Passed, $Message) {
  $script:checks += [pscustomobject]@{ name = $Name; passed = [bool]$Passed; message = $Message }
}
Add-Check 'workspace' (Test-Path $workspace) "$workspace exists."
Add-Check 'evaluation-cases' (Test-Path $evaluationFile) "$evaluationFile exists with the evaluation set."
Add-Check 'evaluation-results' (Test-Path $resultsFile) "$resultsFile contains recorded results."
Add-Check 'instruction-improvement' (Test-Path $improvementFile) "$improvementFile records the improved instructions."
[pscustomobject]@{ passed = @($checks | Where-Object { -not $_.passed }).Count -eq 0; checks = $checks } |
  ConvertTo-Json -Depth 5 -Compress
