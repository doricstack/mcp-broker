#!/bin/bash
# Sourceable archive construction shared by the Linux runner and its contracts.

MUTATION_ARCHIVE_PLACEHOLDERS="var/coverage/.gitkeep var/quality/.gitkeep var/test-logs/.gitkeep"

tar_option_supported() {
  local option="$1"
  local probe_dir
  probe_dir="$(mktemp -d "${TMPDIR:-/tmp}/mcp-broker-tar-probe.XXXXXX")"
  if tar "$option" -cf /dev/null -C "$probe_dir" . >/dev/null 2>&1; then
    rm -rf "$probe_dir"
    return 0
  fi
  rm -rf "$probe_dir"
  return 1
}

mutation_source_archive_build() {
  local root="$1"
  local archive_path="$2"
  local placeholder
  local -a tar_create_options=()
  if tar_option_supported "--no-xattrs"; then
    tar_create_options+=(--no-xattrs)
  fi
  if tar_option_supported "--no-mac-metadata"; then
    tar_create_options+=(--no-mac-metadata)
  fi

  COPYFILE_DISABLE=1 tar \
    "${tar_create_options[@]}" \
    --exclude=".git" \
    --exclude="venv-mcp-broker" \
    --exclude="config/broker.private.yaml" \
    --exclude="var/coverage/*" \
    --exclude="var/quality/*" \
    --exclude="var/test-logs/*" \
    --exclude=".mutmut-cache" \
    --exclude="mutants" \
    --exclude="dist" \
    --exclude="build" \
    -C "$root" \
    -cf "$archive_path" \
    .

  # The excludes above drop these directories by glob, which also drops the
  # placeholders public-export/allowlist.txt names by hand. The container runs the
  # export-completeness contract, so it has to receive them.
  for placeholder in $MUTATION_ARCHIVE_PLACEHOLDERS; do
    if [[ -f "$root/$placeholder" ]]; then
      tar "${tar_create_options[@]}" -rf "$archive_path" -C "$root" "$placeholder"
    fi
  done
}
