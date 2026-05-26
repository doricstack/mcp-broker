# Release Checklist

Use this checklist before tagging a release, applying client config, or telling another user to run `mcp-broker` from this repo.

## Required Gates

Run the public quality gate:

```bash
make quality-gate
```

Required result:
- Line and branch coverage, unit, journey, live, and e2e tiers pass.
- Generated coverage output stays under `var/coverage`.
- No repo-local command depends on private scripts outside this repository.

Run the release gate before tagging:

```bash
make release-gate
```

Required result:
- Package metadata validates.
- Release smoke passes.
- Mutation runs last. On macOS, the release gate uses the Linux container
  mutation target.
- `var/quality/mutation_stats.json` exists.
- Mutation score is 100 and no mutants are `survived`, `no_tests`, `skipped`,
  `suspicious`, `timeout`, `check_was_interrupted_by_user`, `segfault`, or
  `not_checked`.
- PyPI publication workflow runs `make release-gate` before publishing.

When releasing from the private source repo, also run the private export gate:

```bash
make maintainer-release-gate
```

Required result:
- Public release dry-run passes against an exported checkout.
- The exported Makefile has no private maintainer targets.

Run the broker smoke gate:

```bash
make config-validate
make broker-smoke
make linux-container-smoke
make windows-powershell-smoke
make release-smoke
```

Required result:
- The configured YAML passes `config/broker.schema.json` and loader validation.
- Codex, Claude, and Gemini config renders pass in dry-run mode.
- The smoke path does not write client config.
- The daemon can start, answer, and stop through Makefile targets.
- The release smoke starts from a clean tree, uses `make config-init`, and proves the public example does not need private paths.
- Startup service dry-runs pass for macOS LaunchAgent, Linux systemd, and Windows Scheduled Task paths.
- Linux container smoke and Windows PowerShell dry-run smoke pass when Docker and PowerShell are available.

## Config Dry Run

Dry-run both client renders before any apply step:

```bash
make config-render CLIENT=codex CONFIG_RENDER_APPLY=0
make config-render CLIENT=claude CONFIG_RENDER_APPLY=0
make config-render CLIENT=gemini CONFIG_RENDER_APPLY=0
make codex-app-policy CLIENT=codex CODEX_APP_POLICY_APPLY=0
```

Required result:
- Rendered files are written under the runtime render directory.
- Existing client config is not modified.
- Each rendered client has one `mcp-broker` entry.
- Codex app connector policy reports the duplicate app-side connector action it would take.

## Rollback Test

Run the copied-fixture migration tests before touching real client files:

```bash
make test-live
```

The live migration test must exercise `make config-rollback` against copied
Codex, Claude, and Gemini fixtures when those client renderers are present.

If a real client apply has already happened, verify the rollback target exists before running:

```bash
make config-backup CLIENT=codex
make config-rollback CLIENT=codex
```

Repeat with `CLIENT=claude` or `CLIENT=gemini` only when that client wiring is
intended.

Required result:
- Copied fixture rollback restores the original client files.
- Real rollback is used only when a matching backup exists.

## Orphan Process Check

Clean broker-owned leftovers and verify runtime state:

```bash
make broker-stop
make broker-reap
make doctor
```

Required result:
- `make doctor` reports no stale broker-owned resources.
- No broker-owned upstream process group remains after stop or reap.
- No stale broker socket remains without a live owner.

## Release Decision

Do not release or apply client config if any required gate fails.

Release is allowed only when:
- `make quality-gate` passes.
- `make release-gate` passes.
- In the private source repo, `make maintainer-release-gate` passes.
- `make config-validate` passes.
- `make broker-smoke` passes.
- `make linux-container-smoke` passes on a Linux container.
- `make windows-powershell-smoke` passes with PowerShell installed.
- `make release-smoke` passes.
- Config dry run passes for every intended client.
- Rollback test passes.
- `make doctor` reports no stale broker-owned resources.

Maintainers with the private shared quality scripts installed can run the hidden
maintainer gate before release. That gate is not part of the public setup
contract.
