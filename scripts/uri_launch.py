"""Open the existing secure Termylo tunnel from a Windows custom URI.

Only exact start, stop and revoke URIs are accepted. Stop/revoke require
a local Windows confirmation dialog before invoking the fixed Termylo CLI.
Untrusted URI text is never passed to the shell as a command.
"""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
from pathlib import Path

EXPECTED_URI = re.compile(r"termylo://(start|stop|revoke)/?", re.IGNORECASE)


def valid_uri(uri: str) -> bool:
    return isinstance(uri, str) and len(uri) <= 32 and EXPECTED_URI.fullmatch(uri) is not None


def action_from_uri(uri: str) -> str | None:
    if not valid_uri(uri):
        return None
    match = EXPECTED_URI.fullmatch(uri)
    return match.group(1).lower() if match else None


def confirm_local_shutdown(action: str) -> bool:
    """A webpage must not be able to silently stop/revoke local access."""
    if action not in {"stop", "revoke"} or os.name != "nt":
        return False
    noun = "stop the Termylo service" if action == "stop" else "revoke the Termylo approval"
    reply = ctypes.windll.user32.MessageBoxW(
        None, "Do you want to " + noun + " now?",
        "Termylo — local confirmation", 0x00000004 | 0x00000030,
    )
    return reply == 6  # Windows IDYES


def launcher_command(repo: Path, windows_directory: Path) -> list[str]:
    script = repo / "scripts" / "start-tunnel-secure.ps1"
    exe = windows_directory / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not script.is_file():
        raise FileNotFoundError("Termylo secure launcher is missing.")
    if not exe.is_file():
        raise FileNotFoundError("Windows PowerShell was not found.")
    return [
        str(exe), "-NoLogo", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "RemoteSigned", "-File", str(script), "-Headless",
    ]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # No query strings, extra arguments, commands, scripts or other actions.
    if len(args) != 1 or not valid_uri(args[0]):
        return 2
    if os.name != "nt":
        return 3

    action = action_from_uri(args[0])
    repo = Path(__file__).resolve().parents[1]
    windows_directory = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    try:
        if action in {"stop", "revoke"}:
            if not confirm_local_shutdown(action):
                return 0  # User declined; no side effects.
            executable = repo / ".venv" / "Scripts" / "termylo.exe"
            if not executable.is_file():
                return 1
            completed = subprocess.run(
                [str(executable), action], cwd=str(repo), timeout=35,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
            return 0 if completed.returncode == 0 else 1
        command = launcher_command(repo, windows_directory)
        # Launch without creating *any* visible PowerShell console.
        # start-tunnel-secure.ps1 -Headless then creates a console-free tunnel
        # process and exits, leaving no blank/blocked PowerShell host behind.
        subprocess.Popen(
            command,
            cwd=str(repo),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
        return 0
    except (OSError, ValueError):
        # pythonw.exe has no console. No secret-bearing diagnostic output.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
