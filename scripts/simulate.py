"""Safe full-roundtrip simulation. No actual PowerShell or network connection."""
from __future__ import annotations
import json
import threading
import time
from termylo.jobs import JobManager
import termylo.jobs as jobs_module

def wait(manager, jid):
    for _ in range(300):
        r = manager.result(jid)
        if r["status"] != "awaiting_approval_or_running":
            return r
        time.sleep(.01)
    raise RuntimeError("Simulated command failed to finish")

def main():
    real_os = jobs_module.os
    class FakeWindows:
        name = "nt"
    jobs_module.os = FakeWindows()
    try:
        authorization = threading.Event()
        def executor(command, timeout, cancel_event):
            authorization.wait(2)
            if cancel_event.is_set():
                return {"status": "cancelled"}
            return {"status": "completed", "exit_code": 0, "stdout": "Termylo simulation OK\n", "stderr": "", "stdout_truncated": False, "stderr_truncated": False}
        mgr = JobManager(executor)
        request = mgr.submit("Write-Output 'Termylo simulation OK'")
        assert request["status"] == "awaiting_approval"
        assert mgr.result(request["job_id"])["status"] == "awaiting_approval_or_running"
        authorization.set()
        successful = wait(mgr, request["job_id"])
        assert successful["status"] == "completed"
        refused_mgr = JobManager(lambda c, t, cancel_event: {"status": "denied"})
        refused = wait(refused_mgr, refused_mgr.submit("Get-Date")["job_id"])
        invalid = mgr.submit("")
        assert refused["status"] == "denied" and invalid["status"] == "rejected"
        print(json.dumps({"scenario": "MCP -> simulated Windows approval -> output", "submitted": request["status"], "after_approval": successful, "denied": refused["status"], "invalid": invalid["status"], "note": "simulation only; no PowerShell, ChatGPT or remote tunnel was used"}, indent=2))
    finally:
        jobs_module.os = real_os

if __name__ == "__main__":
    main()
