[CmdletBinding()]
param(
    [Parameter()]
    [string]$StdinSqlFile,

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
if ($StdinSqlFile) {
    $resolvedSqlFile = (
        Resolve-Path -LiteralPath $StdinSqlFile -ErrorAction Stop
    ).Path
    if (
        -not (Test-Path -LiteralPath $resolvedSqlFile -PathType Leaf) -or
        [IO.Path]::GetExtension($resolvedSqlFile) -ne ".sql"
    ) {
        throw "StdinSqlFile must be an existing .sql file."
    }
    if ($RemoteCommand.Count -eq 0) {
        throw "A remote migration runner command is required."
    }
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

if ($StdinSqlFile) {
    Get-Content -LiteralPath $resolvedSqlFile -Raw |
        & $sshExecutable @sshArguments
} else {
    & $sshExecutable @sshArguments
}
exit $LASTEXITCODE
