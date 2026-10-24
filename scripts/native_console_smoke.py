"""Prove real interactive powershell.exe can share one persistent process with commands.
No MCP tool is changed by this prototype. Windows owner must already have
approved Termylo's ordinary command tool before running it.
"""
from __future__ import annotations

import json
import os
import secrets
import struct
import subprocess
import time
from pathlib import Path

from termylo.runner import _environment, _system_powershell


def send(pipe_name: str, command: str, *, timeout: float = 8.0) -> dict:
    name = r"\\.\pipe\{}".format(pipe_name)
    deadline = time.monotonic() + timeout
    f = None
    while time.monotonic() < deadline:
        try:
            f = open(name, "r+b", buffering=0)
            break
        except OSError:
            time.sleep(.05)
    if f is None:
        raise RuntimeError("Native PowerShell pipe did not become ready.")
    with f:
        payload = json.dumps({"command": command}).encode("utf-8")
        f.write(struct.pack("<I", len(payload)) + payload)
        f.flush()

        def read_exact(count: int) -> bytes:
            chunks = bytearray()
            while len(chunks) < count:
                block = f.read(count - len(chunks))
                if not block:
                    raise EOFError("PowerShell closed the pipe during response.")
                chunks.extend(block)
            return bytes(chunks)

        size = struct.unpack("<I", read_exact(4))[0]
        if size > 100_000:
            raise RuntimeError("Native PowerShell returned oversized response.")
        return json.loads(read_exact(size).decode("utf-8"))


def main() -> None:
    if os.name != "nt":
        raise RuntimeError("Requires Windows.")
    powershell = _system_powershell()
    assert powershell
    script = Path(__file__).resolve().parents[1] / "termylo" / "native_console.ps1"
    pipe_name = "termylo-" + secrets.token_hex(16)
    proc = subprocess.Popen(
        [powershell, "-NoLogo", "-NoProfile", "-File", str(script), "-PipeName", pipe_name],
        cwd=str(Path.home()),
        env=_environment(),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        stdin=None,
        stdout=None,
        stderr=None,
    )
    print(f"Native PowerShell PID: {proc.pid}", flush=True)
    try:
        for cmd in (
            "Write-Output 'Hello Fenil — this is the native PowerShell console'",
            "$global:TermyloSmokeValue = 'PERSISTENT-STATE-PASSED'",
            "Write-Output $global:TermyloSmokeValue",
            'Set-Location "$HOME\\termylo"',
            "(Get-Location).Path",
        ):
            if proc.poll() is not None:
                raise RuntimeError(f"PowerShell exited unexpectedly: {proc.returncode}")
            result = send(pipe_name, cmd, timeout=8)
            print(json.dumps({"command":cmd,"result":result}, ensure_ascii=False), flush=True)
            if result.get("status") != "completed" or result.get("exit_code") != 0:
                raise RuntimeError(f"Native command failed: {cmd}: {result}")
        # Window remains available for the owner to type manually and close.
        print("NATIVE-SMOKE-PASS: Console remains open for local typing. Type exit to close it.", flush=True)
    except Exception:
        if proc.poll() is None:
            proc.terminate()
        raise


if __name__ == "__main__":
    main()
