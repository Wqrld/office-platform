#!/usr/bin/env python3
"""Every repository path a file names must exist.

    ./tests/refs.py

Scans every tracked text file for `apps/…`, `charts/…`, `policy/…`, `docs/…`, `platform/…`,
`infra/…`, `cluster/…`, `tests/…` and `updatecli/…` paths and fails on any that resolve to
nothing. Globs must match something; `<placeholder>`s and `${VARS}` are skipped. `docs/history/`
and the ADR bodies record decisions as they were made, so they are not scanned. See `AGENTS.md`.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parent.as_posix())
import render  # noqa: E402

ROOT = render.ROOT
TOPS = ("apps", "charts", "policy", "docs", "platform", "infra", "cluster", "tests", "updatecli",
        "examples", "history")
# A path starts at a top-level directory that is not itself the tail of a longer path or URL.
PATH = re.compile(rf"(?<![\w./@-])(?:\./)?((?:{'|'.join(TOPS)})/[\w.*/<>{{}}$+-]*)")
# A relative link in Markdown, resolved from the file's own directory.
LINK = re.compile(r"\]\((?!https?:|mailto:|#)([^)\s#]+)")
# Not scanned: decision records, rendered output, and files that are not ours.
SKIP = ("docs/history/", "docs/adr/", "tests/golden/", "platform/identity/vendor/",
        "docs/maintenance-", "tests/refs.py")
TEXT = (".md", ".yaml", ".yml", ".py", ".sh", ".tpl", ".rego", ".json", ".js", ".txt", ".conf")
TEXT_NAMES = (".sourceignore", ".gitlint", ".gitignore", ".gitattributes", "Chart.lock")
# Things shaped like a path that are not one: apiVersions, and names outside this tree.
API_VERSION = re.compile(r"\w+/v\d+(?:(?:alpha|beta)\d+)?")
NOT_PATHS = {"updatecli/updatecli-action", "updatecli/upstream",   # an action, a branch
             "infra/my-thing.yaml",                                 # updatecli/README's example
             "history/design/adr/000x",                             # AGENTS.md, the pattern
             "docs/spam.md"}       # Messages' upstream docs, from a sizes file (applied verbatim)


def candidates() -> list[str]:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True, capture_output=True,
                           text=True).stdout.split()
    return [f for f in files if not f.startswith(SKIP)
            and (f.endswith(TEXT) or f.rsplit("/", 1)[-1] in TEXT_NAMES)]


def resolves(ref: str, src: str) -> bool:
    ref = ref.rstrip(".,:;)`'\"").split("#")[0]
    if not ref or any(c in ref for c in "<>{}$") or ref in NOT_PATHS or API_VERSION.fullmatch(ref):
        return True
    if ref.startswith("history/"):        # cited from docs/, and by that name everywhere else
        ref = f"docs/{ref}"
    if any(c in ref for c in "*?["):
        return any(ROOT.glob(ref.strip("/")))
    return exists(ROOT / ref)


def exists(p) -> bool:
    # `docs/adr/0106` names the ADR by number, without its slug.
    return p.exists() or (p.parent.exists() and any(p.parent.glob(f"{p.name}-*")))


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    missing = []
    for f in candidates():
        for n, line in enumerate((ROOT / f).read_text(errors="replace").splitlines(), 1):
            if f == ".sourceignore":            # anchored patterns: `/apps/…`
                line = line.removeprefix("/")
            for m in PATH.finditer(line):
                if not resolves(m.group(1), f):
                    missing.append(f"{f}:{n}: {m.group(1)}")
            for m in LINK.finditer(line) if f.endswith(".md") else ():
                if not exists((ROOT / f).parent / m.group(1)):
                    missing.append(f"{f}:{n}: {m.group(1)}")
    for m in missing:
        print(f"  {m}")
    print(f"FAIL — {len(missing)} path(s) name nothing" if missing else "OK — every named path exists")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
