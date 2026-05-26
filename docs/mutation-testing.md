# Mutation Testing

Mutation testing is a release gate, not a quick local loop.

Run it after the public release gates pass:

```bash
make release-gate
```

`release-gate` runs repo-local quality checks, package checks, release smoke,
and then mutation testing as the final step.

The private source repo also has `make maintainer-release-gate`, which runs the
public export dry run before the same final mutation gate.

For mutation only:

```bash
make mutation
```

On macOS release runs use the Linux container mutation target:

```bash
make mutation-linux
```

`make release-gate` selects `mutation-linux` on Darwin and `mutation` on Linux.
This avoids macOS fork-related mutmut failures while still using the same
source tree, `setup.cfg`, and stats checker.

The target runs mutmut against `src/mcp_broker` using public unit and journey
tests, then reads
the generated `mutants/**/*.meta` files with
`scripts/check_mutation_stats.py`.
The mutmut config copies the public docs, config, registry metadata, packaging
assets, workflow files, scripts, `Makefile`, and root public docs into the
mutated workspace because several journey tests enforce those public contracts.

The stats checker writes:

```text
var/quality/mutation_stats.json
```

The JSON report includes top-level counts, the score, and a ranked
`blocked_by_file` list with capped examples for `survived`, `no_tests`, and
other failing statuses. Use that list to fix the largest behavioral gaps
first.

The gate fails when any mutant is:

- `survived`
- `no_tests`
- `skipped`
- `suspicious`
- `timeout`
- `check_was_interrupted_by_user`
- `segfault`
- `not_checked`

The default score threshold is 100. Type-check catches count as passing
mutants. Generated mutation work directories stay out of git:

```text
mutants/
.mutmut-cache/
var/quality/mutation_stats.json
```

## Public Repo Policy

The public repo should include:

- `setup.cfg` mutation configuration
- `make mutation`
- `make mutation-linux`
- `make release-gate`
- `scripts/check_mutation_stats.py`
- `scripts/linux-mutation.sh`
- public-safe tests under `tests/`

The public repo should not include generated mutation output. `mutants/` and
`.mutmut-cache/` are local artifacts and must stay ignored.

## Interpreting Results

Line and branch coverage tell us tests executed code. Mutation testing checks
whether tests reject changed behavior.

Do not treat mutmut's process exit code alone as proof. The release gate is the
JSON stats check. A run with `0 survived` but thousands of `segfault` or
`not_checked` mutants fails because it did not prove the suite killed those
mutants.

## Scope

The default mutation selector uses public unit and journey tests. Local e2e
tests stay in `make quality-gate`, not mutmut, because they spawn console
entrypoints in subprocesses. Mutmut's instrumentation requires an in-process
runner; subprocess imports of instrumented modules crash during stats
collection before mutant execution. Private contract tests are excluded with
the `private_contract` marker because they validate the maintainer export
pipeline and private runbooks, not public broker behavior.

Public CI can run `make quality-gate` on every PR and reserve `make
release-gate` for tagged releases, protected release branches, or manual
maintainer runs.
