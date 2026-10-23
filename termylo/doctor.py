"""Read-only checks for Windows environment. Does not connect or execute commands."""
from __future__ import annotations
import os
import shutil
import sys
from pathlib import Path

def report() -> dict:
    workdir = Path(os.getenv("TERMYLO_WORKDIR", str(Path.home()))).expanduser()
    try:
        import tkinter  # noqa: F401
        tkinter_available = True
    except (ImportError, RuntimeError):
        tkinter_available = False
    try:
        import mcp  # noqa: F401
        mcp_available = True
    except ImportError:
        mcp_available = False
    return {
        "platform": sys.platform, "python": sys.version.split()[0],
        "powershell_found": bool(shutil.which("powershell.exe")),
        "tkinter_found": tkinter_available, "mcp_sdk_found": mcp_available,
        "workdir_exists": workdir.is_dir(), "workdir": str(workdir),
        "elevated_check": "Run from an ordinary non-administrator Windows account.",
        "network_listener": "none (stdio only)",
    }

def main() -> None:
    import json
    print(json.dumps(report(), indent=2))

if __name__ == "__main__":
    main()
