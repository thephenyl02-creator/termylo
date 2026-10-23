"""Run ONLY on the owner's Windows desktop: manually verify real approval dialog.

This script does not use ChatGPT or a remote tunnel.
It runs a harmless Write-Output command only after the user approves locally.
"""
from __future__ import annotations

import json
import os
import sys

from termylo.runner import run_command

def main() -> int:
    if os.name != "nt":
        print("This manual GUI test must be run in an interactive Windows desktop session.")
        return 2
    print("A Windows approval dialog will appear. Choose APPROVE ONCE to test the PowerShell round-trip.")
    result = run_command("Write-Output 'Termylo GUI approval verified'", 15)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if (
        result.get("status") == "completed"
        and result.get("exit_code") == 0
        and "Termylo GUI approval verified" in result.get("stdout", "")
    ):
        print("PASS: Windows approval popup and execution round-trip succeeded.")
        return 0
    print("NOT VERIFIED: GUI approval was denied, failed, timed out, or returned unexpected output.")
    return 1

if __name__ == "__main__":
    sys.exit(main())
