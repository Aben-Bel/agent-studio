import importlib, pathlib
from .util import log


def discover(packages=("agents", "tools", "skills", "connectors", "mcp", "pipeline", "exporters")):
    """Import every module under each package - including SUBFOLDERS - so its
    @agent/@tool/@skill/@mcp decorators run and self-register.

    Recursing into subfolders is what lets many people work in parallel: each
    person gets their own subfolder (e.g. tools/alice/foo.py, tools/bob/bar.py)
    and nobody edits a shared registry file, so there are no merge conflicts.
    Subfolders do not need an __init__.py - they import as namespace packages."""
    for pkg in packages:
        root = pathlib.Path(pkg)
        if not root.exists():
            continue
        for mod in sorted(root.rglob("*.py")):
            if mod.stem == "__init__" or "__pycache__" in mod.parts:
                continue
            dotted = ".".join(mod.with_suffix("").parts)   # tools/alice/foo.py -> tools.alice.foo
            try:
                importlib.import_module(dotted)
                log.info("discovered %s", dotted)
            except Exception as e:
                # One broken contributor file must not take down discovery for
                # everyone else. Log it and keep going.
                log.warning("skipped %s: %s", dotted, e)
