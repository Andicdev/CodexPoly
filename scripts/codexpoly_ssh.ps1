[CmdletBinding()]
param(
    [Parameter(
        Position = 0,
        ValueFromRemainingArguments = $true
    )]
    [string[]]$RemoteCommand,

    [Parameter()]
    [ValidateSet("host01", "host02")]
    [string]$Target = "host01",

    [Parameter()]
    [string]$StdinSqlFile,

    [Parameter()]
    [switch]$Interactive
)

$ErrorActionPreference = "Stop"

$sshExecutable = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$identityFile = Join-Path $env:USERPROFILE `
    ".ssh\codexpoly_lightsail_ed25519"
$deploymentTargets = @{
    host01 = "52.16.49.33"
    host02 = "54.73.200.228"
}
$targetHost = $deploymentTargets[$Target]

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
if ($Interactive -and $StdinSqlFile) {
    throw "Interactive mode cannot be combined with StdinSqlFile."
}

$sshArguments = @(
    "-i", $identityFile,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=12",
    "-o", "StrictHostKeyChecking=yes",
    "-o", "KexAlgorithms=curve25519-sha256"
)
if ($Interactive) {
    $sshArguments += "-tt"
}
$sshArguments += "codexdeploy@$targetHost"

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
