$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$logPath = 'C:\image-build.log'

Start-Transcript -Path $logPath -Append
try {
    $choco = Get-Command choco.exe -ErrorAction SilentlyContinue
    if (-not $choco) {
        Set-ExecutionPolicy Bypass -Scope Process -Force
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-Expression ((New-Object Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
            [Environment]::GetEnvironmentVariable('Path', 'User')
        $choco = Get-Command choco.exe -ErrorAction Stop
    }

    & $choco.Source install vscode python312 git azure-cli -y --no-progress
    if ($LASTEXITCODE -ne 0) {
        throw "Chocolatey package installation failed with exit code $LASTEXITCODE."
    }

    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $pythonPath = 'C:\Python312'
    $pythonScriptsPath = Join-Path $pythonPath 'Scripts'
    $machinePathEntries = @($machinePath -split ';' | Where-Object { $_ })
    foreach ($pathEntry in @($pythonPath, $pythonScriptsPath)) {
        if ($machinePathEntries -notcontains $pathEntry) {
            $machinePathEntries += $pathEntry
        }
    }
    [Environment]::SetEnvironmentVariable('Path', ($machinePathEntries -join ';'), 'Machine')

    $codePath = Join-Path ${env:ProgramFiles} 'Microsoft VS Code\bin\code.cmd'
    if (-not (Test-Path $codePath)) {
        throw 'The machine-wide VS Code installation was not found.'
    }

    $extensionsPath = 'C:\VSCodeExtensions'
    New-Item -ItemType Directory -Path $extensionsPath -Force | Out-Null
    $foundryToolkitExtension = 'ms-windows-ai-studio.windows-ai-studio'
    $extensions = @(
        'ms-python.python',
        'ms-toolsai.jupyter',
        $foundryToolkitExtension
    )
    foreach ($extension in $extensions) {
        & $codePath --install-extension $extension --force --extensions-dir $extensionsPath
        if ($LASTEXITCODE -ne 0) {
            throw "VS Code extension installation failed: $extension."
        }
    }

    [Environment]::SetEnvironmentVariable('VSCODE_EXTENSIONS', $extensionsPath, 'Machine')
    [Environment]::SetEnvironmentVariable(
        'LABFORGE_FOUNDRY_EXTENSION_ID',
        $foundryToolkitExtension,
        'Machine'
    )
    & icacls.exe $extensionsPath /grant '*S-1-5-32-545:(OI)(CI)RX' /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not grant standard users read access to the shared VS Code extensions.'
    }

    New-Item -ItemType Directory -Path 'C:\Labs' -Force | Out-Null
    $publicDesktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
    $shortcutPath = Join-Path $publicDesktop 'LabForge Labs.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $codePath
    $shortcut.Arguments = '--extensions-dir "' + $extensionsPath + '" C:\Labs'
    $shortcut.WorkingDirectory = 'C:\Labs'
    $shortcut.Save()

    New-ItemProperty `
        -Path 'HKLM:\SOFTWARE\Microsoft\ServerManager' `
        -Name 'DoNotOpenAtLogon' `
        -PropertyType DWord `
        -Value 1 `
        -Force | Out-Null

    $ieEscPath = 'HKLM:\SOFTWARE\Microsoft\Active Setup\Installed Components\{AEB6717E-7E19-11D0-97EE-00C04FD91972}'
    if (Test-Path $ieEscPath) {
        New-ItemProperty -Path $ieEscPath -Name 'IsInstalled' -PropertyType DWord -Value 0 -Force | Out-Null
    }

}
finally {
    Stop-Transcript
}
