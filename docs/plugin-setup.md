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

The plugin defaults to `PLUGIN_CLIENT=codex`. Override it only when the target
client profile exists in the active broker config:

```bash
make plugin-render PLUGIN_CLIENT=codex
```

The plugin targets never bypass the normal broker commands. They call `setup`,
`broker-status`, `config-render`, and `config-rollback`, which keeps validation,
runtime layout, backups, and rollback behavior in the same path used by the rest
of the project.
