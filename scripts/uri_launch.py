"""Open the existing secure Termylo tunnel from a Windows custom URI.

This handler intentionally supports ONE operation: termylo://start.
Untrusted URI text is never interpolated into commands or forwarded to PowerShell.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

EXPECTED_URI = re.compile(r"termylo://start/?", re.IGNORECASE)


def valid_uri(uri: str) -> bool:
    return isinstance(uri, str) and len(uri) <= 32 and EXPECTED_URI.fullmatch(uri) is not None


def launcher_command(repo: Path, windows_directory: Path) -> list[str]:
    script = repo / "scripts" / "start-tunnel-secure.ps1"
    exe = windows_directory / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not script.is_file():
        raise FileNotFoundError("Termylo secure launcher is missing.")
    if not exe.is_file():
        raise FileNotFoundError("Windows PowerShell was not found.")
    return [
        str(exe), "-NoLogo", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "RemoteSigned", "-File", str(script),
    ]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # No query strings, extra arguments, commands, scripts or other actions.
    if len(args) != 1 or not valid_uri(args[0]):
        return 2
    if os.name != "nt":
        return 3

    repo = Path(__file__).resolve().parents[1]
    windows_directory = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    try:
        command = launcher_command(repo, windows_directory)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_SHOWMINIMIZED
        subprocess.Popen(
            command,
            cwd=str(repo),
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            startupinfo=startup,
            close_fds=True,
        )
        return 0
    except (OSError, ValueError):
        # pythonw.exe has no console. No secret-bearing diagnostic output.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
