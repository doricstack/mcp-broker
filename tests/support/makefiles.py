from pathlib import Path
import re


def read_combined_makefiles(root: Path) -> str:
    root_makefile = root / "Makefile"
    text = root_makefile.read_text(encoding="utf-8")
    included_parts: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("include $(ROOT)/mk/"):
            continue
        relative = stripped.removeprefix("include $(ROOT)/")
        included_parts.append((root / relative).read_text(encoding="utf-8"))
    return "\n".join([text, *included_parts])


def read_make_variable_defaults(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in read_combined_makefiles(root).splitlines():
        match = re.match(r"^([A-Z0-9_]+)\s*\?=\s*(.*)$", line)
        if not match:
            continue
        values[match.group(1)] = match.group(2).strip()
    return values


def expand_make_value(values: dict[str, str], value: str) -> str:
    expanded = value
    for _ in range(10):
        next_value = re.sub(
            r"\$\(([A-Z0-9_]+)\)",
            lambda match: values.get(match.group(1), match.group(0)),
            expanded,
        )
        if next_value == expanded:
            return expanded
        expanded = next_value
    return expanded
