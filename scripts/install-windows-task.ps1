param(
    [switch]$Apply,
    [switch]$DryRun,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    @"
usage: install-windows-task.ps1 [-DryRun|-Apply] [-Help]

Renders or registers a Windows Scheduled Task for mcp-broker. DryRun is the default.

Environment:
  MCP_BROKER_RUNTIME_ROOT      Runtime root, default: %USERPROFILE%\mcp\mcp-broker
  MCP_BROKER_SOCKET            Broker socket path
  MCP_BROKER_CONFIG            Broker config path
  MCP_BROKER_DAEMON_COMMAND    Optional daemon command override
  MCP_BROKER_WINDOWS_TASK      Task name, default: mcp-broker
"@
    exit 0
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeRoot = if ($env:MCP_BROKER_RUNTIME_ROOT) { $env:MCP_BROKER_RUNTIME_ROOT } else { Join-Path $env:USERPROFILE "mcp\mcp-broker" }
$SocketPath = if ($env:MCP_BROKER_SOCKET) { $env:MCP_BROKER_SOCKET } else { Join-Path $RuntimeRoot "sockets\broker.sock" }
$ConfigPath = if ($env:MCP_BROKER_CONFIG) { $env:MCP_BROKER_CONFIG } else { Join-Path $Root "config\broker.example.yaml" }
$TaskName = if ($env:MCP_BROKER_WINDOWS_TASK) { $env:MCP_BROKER_WINDOWS_TASK } else { "mcp-broker" }
$Mode = if ($Apply -and -not $DryRun) { "apply" } else { "dry-run" }
$RenderPath = Join-Path $RuntimeRoot "renders\windows-task-$TaskName.txt"
$BackupPath = ""

function Get-DaemonCommand {
    if ($env:MCP_BROKER_DAEMON_COMMAND) {
        return $env:MCP_BROKER_DAEMON_COMMAND
    }
    $RepoPython = Join-Path $Root "venv-mcp-broker\Scripts\python.exe"
    if (Test-Path $RepoPython) {
        return "$RepoPython -m mcp_broker.daemon"
    }
    $Command = Get-Command "mcp-broker-daemon" -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }
    return "mcp-broker-daemon"
}

function Write-Plan {
    param([string]$TargetPath)
    $DaemonCommand = Get-DaemonCommand
    New-Item -ItemType Directory -Force -Path (Split-Path $TargetPath) | Out-Null
    @"
TaskName=$TaskName
WorkingDirectory=$Root
MCP_BROKER_RUNTIME_ROOT=$RuntimeRoot
MCP_BROKER_SOCKET=$SocketPath
MCP_BROKER_CONFIG=$ConfigPath
Command=$DaemonCommand serve --runtime-root $RuntimeRoot --socket-path $SocketPath --config $ConfigPath
"@ | Set-Content -Path $TargetPath -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

$Smoke = Start-Process -FilePath "make" -ArgumentList @(
    "-C", $Root,
    "broker-smoke",
    "RUNTIME_ROOT=$RuntimeRoot",
    "SOCKET_PATH=$SocketPath",
    "CONFIG_PATH=$ConfigPath"
) -NoNewWindow -Wait -PassThru

if ($Smoke.ExitCode -ne 0) {
    Write-Error "broker-smoke failed; refusing Windows Scheduled Task install"
    exit $Smoke.ExitCode
}

if ($Mode -eq "dry-run") {
    Write-Plan -TargetPath $RenderPath
    Write-Output "dry_run=true rendered_path=$RenderPath task_name=$TaskName"
    exit 0
}

$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    $BackupDir = Join-Path $RuntimeRoot "backups\windows-task"
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $BackupPath = Join-Path $BackupDir "$Stamp.$TaskName.txt"
    Write-Plan -TargetPath $BackupPath
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$DaemonCommand = Get-DaemonCommand
$Parts = $DaemonCommand.Split(" ", 2)
$Executable = $Parts[0]
$PrefixArgs = if ($Parts.Count -gt 1) { $Parts[1] } else { "" }
$DaemonArgs = "$PrefixArgs serve --runtime-root `"$RuntimeRoot`" --socket-path `"$SocketPath`" --config `"$ConfigPath`"".Trim()
$Action = New-ScheduledTaskAction -Execute $Executable -Argument $DaemonArgs -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "mcp-broker local MCP daemon" | Out-Null

Write-Output "dry_run=false task_name=$TaskName backup_path=$BackupPath"
