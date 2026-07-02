# Plugin Setup

The Codex plugin surface is defined by `.codex-plugin/plugin.json`. The plugin
uses repo-owned Make targets so the same commands work from a clone, an
installed package checkout, or an enterprise-managed workstation.

Run the setup target first:

```bash
make plugin-install
```

Check the local broker:

```bash
make plugin-status
```

Dry-run the client config render:

```bash
make plugin-render
```

`make plugin-render` delegates to `config-render` with `CONFIG_RENDER_APPLY=0`.
No client config is written unless the apply flag is explicit.

Apply the rendered config only after review:

```bash
make plugin-apply PLUGIN_APPLY=1
```

Roll back the latest client config backup only after review:

```bash
make plugin-rollback PLUGIN_APPLY=1
```

Runtime bootstrap has separate approval-gated targets:

```bash
make plugin-bootstrap-preflight BOOTSTRAP_METADATA=path/to/runtime-metadata.json
make plugin-bootstrap-plan BOOTSTRAP_METADATA=path/to/runtime-metadata.json
make plugin-bootstrap-apply BOOTSTRAP_METADATA=path/to/runtime-metadata.json BOOTSTRAP_APPROVED=1
make plugin-bootstrap-status
make plugin-bootstrap-rollback BOOTSTRAP_APPROVED=1
make plugin-bootstrap-uninstall BOOTSTRAP_APPROVED=1
```

Preflight and plan do not write active runtime pointers. Apply, rollback, and
uninstall require `BOOTSTRAP_APPROVED=1`. Apply activates the runtime extracted
from the verified archive, not a caller-supplied unpacked directory, and the
active pointer moves only after the entrypoint smoke check passes.

Service bootstrap also has a generic dry-run plan:

```bash
make service-plan SERVICE_PLAN_PLATFORM=macos MCP_BROKER_DAEMON_COMMAND="$(command -v mcp-broker-daemon)"
make service-plan SERVICE_PLAN_PLATFORM=linux MCP_BROKER_DAEMON_COMMAND="$(command -v mcp-broker-daemon)"
make service-plan SERVICE_PLAN_PLATFORM=windows MCP_BROKER_DAEMON_COMMAND="$(command -v mcp-broker-daemon)"
```

The service plan prints target paths, render paths, environment, and daemon
command for LaunchAgent, systemd user service, or Windows Scheduled Task setup.
It is non-mutating and reports `would_mutate=false`; use the platform-specific
apply flag only after reviewing the plan.

The plugin defaults to `PLUGIN_CLIENT=codex`. Override it only when the target
client profile exists in the active broker config:

```bash
make plugin-render PLUGIN_CLIENT=codex
```

The plugin targets never bypass the normal broker commands. They call `setup`,
`broker-status`, `config-render`, and `config-rollback`, which keeps validation,
runtime layout, backups, and rollback behavior in the same path used by the rest
of the project.
