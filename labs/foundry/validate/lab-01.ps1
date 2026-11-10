$ErrorActionPreference = 'Stop'
$checks = @()

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][bool]$Passed,
        [Parameter(Mandatory = $true)][string]$Message
    )

    $script:checks += [pscustomobject]@{
        name = $Name
        passed = $Passed
        message = $Message
    }
}

$python = Get-Command python.exe -ErrorAction SilentlyContinue
Add-Check 'python' ($null -ne $python) 'Python is available on PATH.'

$git = Get-Command git.exe -ErrorAction SilentlyContinue
Add-Check 'git' ($null -ne $git) 'Git is available on PATH.'

$code = Join-Path ${env:ProgramFiles} 'Microsoft VS Code\bin\code.cmd'
$extensionsPath = [Environment]::GetEnvironmentVariable('VSCODE_EXTENSIONS', 'Machine')
$foundryExtensionId = [Environment]::GetEnvironmentVariable('LABFORGE_FOUNDRY_EXTENSION_ID', 'Machine')
$extensionIds = @()
if ((Test-Path $code) -and $extensionsPath -and (Test-Path $extensionsPath)) {
    $extensionIds = @(& $code --list-extensions --extensions-dir $extensionsPath)
}
$foundryExtension = $foundryExtensionId -and ($extensionIds -contains $foundryExtensionId)
Add-Check 'foundry-toolkit' $foundryExtension 'Microsoft Foundry Toolkit is installed in the shared extension directory.'

$labPath = 'C:\Labs\lab1'
$hasGitCommit = $false
if (Test-Path (Join-Path $labPath '.git')) {
    $previousLocation = Get-Location
    try {
        Set-Location $labPath
        & git.exe rev-parse --verify HEAD *> $null
        $hasGitCommit = $LASTEXITCODE -eq 0
    }
    finally {
        Set-Location $previousLocation
    }
}
Add-Check 'lab1-first-commit' $hasGitCommit 'C:\Labs\lab1 has a Git repository with at least one commit.'

$failedChecks = @($checks | Where-Object { -not $_.passed })
[pscustomobject]@{
    passed = $failedChecks.Count -eq 0
    checks = $checks
} | ConvertTo-Json -Depth 5 -Compress
