"""Owner-device acceptance test for the actual MCP job-worker execution path.

No ChatGPT, remote tunnel, or unsafe command is involved. Only a harmless
Write-Output command will be run after local approval on Windows.
"""
from __future__ import annotations

import json
import os
import sys
import time

from termylo.jobs import JobManager

COMMAND = "Write-Output 'Termylo GUI approval verified'"
EXPECTED = "Termylo GUI approval verified"

def main() -> int:
    if os.name != "nt":
        print("An interactive, non-administrator Windows desktop is required.")
        return 2

    manager = JobManager()
    print("Review the on-screen Termylo popup and click APPROVE ONCE for the harmless command.", flush=True)
    submitted = manager.submit(COMMAND, timeout_seconds=60)
    if submitted.get("status") != "awaiting_approval":
        print(json.dumps(submitted, ensure_ascii=False, indent=2))
        return 1

    job_id = submitted["job_id"]
    deadline = time.monotonic() + 150  # 60s approval + 60s command + margin
    result = {"status": "not_finished"}
    while time.monotonic() < deadline:
        result = manager.result(job_id)
        if result.get("status") != "awaiting_approval_or_running":
            break
        time.sleep(0.1)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if (
        result.get("status") == "completed"
        and result.get("exit_code") == 0
        and EXPECTED in result.get("stdout", "")
    ):
        print("PASS: Async command submission, on-device approval, PowerShell and result retrieval.")
        return 0

    if result.get("status") == "awaiting_approval_or_running":
        manager.cancel(job_id)
    print("NOT VERIFIED: No approved and successful end-to-end Windows command was observed.")
    return 1

if __name__ == "__main__":
    sys.exit(main())
