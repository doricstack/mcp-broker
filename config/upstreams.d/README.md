# Upstream Catalog

`broker.private.yaml` is the private runtime config. `broker.example.yaml` is
the public template and must stay free of private upstream inventory.

Once implementation starts, per-upstream files in this directory will become
the editable catalog source.

Rules:
- Keep every upstream setting in config, not source code.
- Store auth and browser state under `~/mcp/mcp-broker/state/upstreams/<name>/`.
- Store secrets under `~/mcp/mcp-broker/secrets/`.
- Mark risky or session-bound upstreams as `per_session` until tested.
