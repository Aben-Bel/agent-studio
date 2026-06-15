import importlib, pathlib
from .util import log


def discover(packages=("agents", "tools", "skills", "connectors")):
    """Import every module in each package so its @agent/@tool/@skill
    decorators run and self-register. This is what lets 8 people add files
    in parallel without editing any shared registry file."""
    for pkg in packages:
        p = pathlib.Path(pkg)
        if not p.exists():
            continue
        for mod in sorted(p.glob("*.py")):
            if mod.stem == "__init__":
                continue
            importlib.import_module(f"{pkg}.{mod.stem}")
            log.info("discovered %s.%s", pkg, mod.stem)
