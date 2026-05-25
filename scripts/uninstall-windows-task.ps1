param(
    [switch]$Apply,
    [switch]$DryRun,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    @"
usage: uninstall-windows-task.ps1 [-DryRun|-Apply] [-Help]

Plans or removes the mcp-broker Windows Scheduled Task. DryRun is the default.
"@
    exit 0
}

$RuntimeRoot = if ($env:MCP_BROKER_RUNTIME_ROOT) { $env:MCP_BROKER_RUNTIME_ROOT } else { Join-Path $env:USERPROFILE "mcp\mcp-broker" }
$TaskName = if ($env:MCP_BROKER_WINDOWS_TASK) { $env:MCP_BROKER_WINDOWS_TASK } else { "mcp-broker" }
$Mode = if ($Apply -and -not $DryRun) { "apply" } else { "dry-run" }
$PlanPath = Join-Path $RuntimeRoot "renders\uninstall-windows-task-$TaskName.txt"

if ($Mode -eq "dry-run") {
    New-Item -ItemType Directory -Force -Path (Split-Path $PlanPath) | Out-Null
    "TaskName=$TaskName" | Set-Content -Path $PlanPath -Encoding UTF8
    Write-Output "dry_run=true plan_path=$PlanPath task_name=$TaskName"
    exit 0
}

$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Write-Output "dry_run=false task_name=$TaskName"
