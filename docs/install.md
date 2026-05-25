# Install mcp-broker

`mcp-broker` is a local MCP process broker. It keeps one broker daemon running,
then exposes one lightweight client shim to MCP clients.

## Prerequisites

- macOS with `launchctl`
- Python 3.10 or newer available as `python3`
- `make`
- Node.js and `npx` for upstream MCPs that use npm packages
- A clone of this repo

Run every setup, test, runtime, and client-wiring command through the Makefile.

## Install Options

For a source checkout, use the Makefile flow below. This is the current
supported install path for local development and validation.

The package path is intended to be:

```bash
pipx install mcp-broker
```

After a PyPI package exists, `pipx` should put `mcp-broker-client` and
`mcp-broker-daemon` on the user's PATH. It also installs the top-level
`mcp-broker` command:

```bash
mcp-broker init
mcp-broker start
mcp-broker status
mcp-broker render codex --dry-run
```

For service managers, set `MCP_BROKER_DAEMON_COMMAND` to the installed daemon
path when the repo-local venv is not used.

The `uv` path should use the same package after the PyPI release exists:

```bash
uv tool install mcp-broker
uvx mcp-broker status
```

Homebrew is planned as a formula or tap after the package release:

```bash
brew install mcp-broker
```

The Homebrew formula should install the same console scripts and use the same
runtime root contract. It should not write MCP client config during package
install.

Windows uses a PowerShell Scheduled Task. It follows the same runtime-root and
config contract as macOS and Linux.

## Create Private Config

Start from the public template, then edit the private runtime file for local
upstreams, paths, profiles, and secret variable names.

```bash
make config-init
```

`config-init` creates the private config destination directory when needed and
copies the public example template as the starting point. It does not import
local MCP inventory, user paths, or secrets.

Keep secret values out of both files. Use environment variable names under
`upstreams.<name>.env` or runtime secret files under:

```text
$HOME/mcp/mcp-broker/secrets/
```

## Setup

```bash
make setup
make config-validate
make quality-gate
```

`make setup` creates `venv-mcp-broker`, installs dependencies, and verifies the
runtime layout under:

```text
$HOME/mcp/mcp-broker/
```

## Install LaunchAgent

Render and smoke-test the LaunchAgent without writing it:

```bash
make launchagent-install
```

Apply it after the smoke passes:

```bash
make launchagent-install LAUNCHAGENT_APPLY=1
make launchagent-load
```

Verify daemon health:

```bash
make doctor
make broker-status
```

## Install systemd User Service

Linux uses the same runtime-root contract as macOS:

```bash
make systemd-install
```

That renders a service preview under `$HOME/mcp/mcp-broker/renders/` and runs
`make broker-smoke` first. Apply it only after reviewing the render:

```bash
make systemd-install SYSTEMD_APPLY=1
make systemd-load
```

For package installs, pass the installed daemon command:

```bash
make systemd-install SYSTEMD_APPLY=1 MCP_BROKER_DAEMON_COMMAND="$(command -v mcp-broker-daemon)"
make systemd-load
```

Unload or remove it with:

```bash
make systemd-unload
make systemd-uninstall SYSTEMD_APPLY=1
```

## Install Windows Scheduled Task

Windows startup uses PowerShell Scheduled Task commands:

```powershell
make windows-install
make windows-install WINDOWS_APPLY=1
make windows-load
```

`make windows-install` is dry-run by default and writes a plan under the runtime
render directory. Apply only after reviewing that plan.

For package installs, pass the installed daemon command:

```powershell
make windows-install WINDOWS_APPLY=1 MCP_BROKER_DAEMON_COMMAND="$(Get-Command mcp-broker-daemon).Source"
make windows-load
```

Remove the task with:

```powershell
make windows-unload
make windows-uninstall WINDOWS_APPLY=1
```

## Wire A Client

Back up the client config first:

```bash
make config-backup CLIENT=codex
```

Dry-run the render:

```bash
make config-render CLIENT=codex CONFIG_RENDER_APPLY=0
```

Apply only after reviewing the rendered file under
`$HOME/mcp/mcp-broker/renders/`:

```bash
make config-render CLIENT=codex CONFIG_RENDER_APPLY=1
```

To write a per-project client config instead of the client path from broker
config:

```bash
make config-render CLIENT=codex CONFIG_RENDER_APPLY=1 CONFIG_RENDER_TARGET_PATH="$HOME/.codex/configs/config.project.toml"
```

Use that for launchers that maintain per-project Codex settings. The MCP server
list still comes from broker config only; do not sync MCP lists between Codex and
Claude.

If `codex_apps` duplicates broker-owned connectors after a Codex cache refresh,
reapply the config-backed app connector policy:

```bash
make codex-app-policy CLIENT=codex CODEX_APP_POLICY_APPLY=1
```

`make config-render CLIENT=codex CONFIG_RENDER_APPLY=1` also applies that
policy after writing the Codex config.

Use the same targets with `CLIENT=claude` only after the Claude profile smoke
passes and you intend to wire Claude.

## Rollback

```bash
make config-rollback CLIENT=codex
make doctor
```

Use `CLIENT=claude` to restore the latest Claude backup.

## Smoke Checks

```bash
make config-validate
make tools-count PROFILE=codex
make codex-facade-smoke
make claude-facade-smoke
make codex-profile-validation
make codex-claude-discovery-parity
make codex-deferred-acceptance
make broker-smoke
make linux-container-smoke
make windows-powershell-smoke
make release-smoke
make doctor
```

`make claude-facade-smoke` does not write Claude config. It only verifies the
Claude profile through the broker shim.

`make codex-claude-discovery-parity` compares Codex and Claude compact profile
discovery through the client shim without writing Claude config. It checks
compact `tools/list`, `broker.status`, search, describe, and one configured safe
broker-mediated call.

`make profile-validation PROFILE=<profile>` is the config-driven upstream gate.
It loads enabled upstreams from YAML and validates each profile-visible upstream
with its configured `smoke` probe. It fails when the YAML omits a safe probe.

`make config-validate` checks the selected YAML against
`config/broker.schema.json` and then loads it through the broker runtime parser.
Use it after editing `config/broker.private.yaml` and before any client render.

Direct Codex deferred-tool checks are manual acceptance, not public repo gates.
Do not put `codex exec` in `make quality-gate`; it invokes an external LLM
session and can change with account, network, model, or hosted connector state.
Use the broker-owned Make targets for deterministic validation.

`make release-smoke` creates a clean tree from tracked files, copies the public
example through `make config-init`, validates it, and runs `make broker-smoke`
with a temporary runtime root. It is the public install-path proof that the repo
does not need private paths.

`make linux-container-smoke` downloads the configured Linux Python image when
missing, then runs the public setup path and systemd dry-run inside that
container.

`make windows-powershell-smoke` validates the PowerShell Scheduled Task scripts
with dry-run mode. On non-Windows machines it does not register a task.

`make codex-deferred-acceptance` reads the same YAML `smoke` probes and prints
the exact `mcp__mcp_broker__` wrapper calls to run inside an active Codex
session. It does not call Codex and it does not write client config.

Manual `/mcp` acceptance checklist:

- Codex shows one `mcp-broker` entry.
- Codex shows broker tools, not raw upstream tool lists.
- `codex_apps` excludes connectors disabled by the configured app policy.
- A direct client call to `broker.status` returns the profile-visible upstreams.
- `make codex-profile-validation` passes against the same config.

Use the same checklist for Claude only after the user approves Claude wiring.
Before that point, use `make claude-profile-validation` without applying Claude
config.

## Stop Or Reap

```bash
make broker-stop
make broker-reap
make doctor
```

`make doctor` must report no stale broker-owned resources before and after
client wiring.
