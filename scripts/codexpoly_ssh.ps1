[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemoteCommand
)

$ErrorActionPreference = "Stop"

$sshExecutable = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$identityFile = Join-Path $env:USERPROFILE `
    ".ssh\codexpoly_lightsail_ed25519"

if (-not (Test-Path -LiteralPath $sshExecutable -PathType Leaf)) {
    throw "Windows OpenSSH client is not installed."
}
if (-not (Test-Path -LiteralPath $identityFile -PathType Leaf)) {
    throw "CodexPoly deployment identity is not installed."
}

$sshArguments = @(
    "-i", $identityFile,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=12",
    "-o", "StrictHostKeyChecking=yes",
    "codexdeploy@52.16.49.33"
)

if ($RemoteCommand.Count -gt 0) {
    $sshArguments += "--"
    $sshArguments += $RemoteCommand
}

& $sshExecutable @sshArguments
exit $LASTEXITCODE
