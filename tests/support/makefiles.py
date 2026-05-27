from pathlib import Path


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
