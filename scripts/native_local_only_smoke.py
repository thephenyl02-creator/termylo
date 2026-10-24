"""Owner-device smoke test: expire remote IPC while keeping native PowerShell open.

Launches a disposable visible PowerShell window; closes it at the end.
Does not request new access or change the running Termylo service.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import threading
import time
from pathlib import Path

from termylo.native import _native_exchange
from termylo.runner import _environment, _system_powershell, _terminate_tree


def main() -> None:
    if os.name != "nt":
        raise RuntimeError("Windows only")
    powershell = _system_powershell()
    assert powershell
    script = Path(__file__).resolve().parents[1] / "termylo" / "native_console.ps1"
    pipe_name = "termylo-" + secrets.token_hex(20)
    proc = subprocess.Popen(
        [powershell, "-NoLogo", "-NoProfile", "-File", str(script), "-PipeName", pipe_name],
        cwd=str(Path.home()), env=_environment(),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    try:
        def call(command: str) -> dict:
            return _native_exchange(pipe_name, command, time.monotonic() + 10, threading.Event())

        first = call("Write-Output 'LOCAL_ONLY_TEST'")
        assert first["exit_code"] == 0 and "LOCAL_ONLY_TEST" in first["stdout"], first
        revoke = call("__TERMYLO_REVOKE_IPC__")
        assert revoke["exit_code"] == 0 and "LOCAL ONLY" in revoke["stdout"], revoke
        time.sleep(0.25)
        assert proc.poll() is None, "Window exited after remote authority revoked."
        try:
            with open(r"\\.\pipe\{}".format(pipe_name), "r+b", buffering=0):
                raise AssertionError("Named pipe still accepting connections.")
        except OSError:
            pass
        print("PASS: IPC revoked; native PowerShell remains open locally.", flush=True)
    finally:
        if proc.poll() is None:
            _terminate_tree(proc)


if __name__ == "__main__":
    main()
