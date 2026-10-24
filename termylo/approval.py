"""Owner-controlled approval UI, isolated from MCP worker threads.

Tkinter/Tcl is created, used and destroyed only on the **main thread of a
dedicated child Python process**. The MCP worker never imports tkinter.
The parent accepts only an exit code of 0 as approval and denies everything
else, including a failed GUI, process crash, timeout or cancellation.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from .runner import MAX_COMMAND, _environment

APPROVAL_TIMEOUT_SECONDS = 60
PROCESS_GRACE_SECONDS = 5
MAX_INPUT_BYTES = MAX_COMMAND * 4


def _stop_process(proc: subprocess.Popen) -> None:
    """Best-effort cleanup for an approval-only child (never the PowerShell job)."""
    try:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        pass


def ask_local_user(command: str, cancel_event: threading.Event) -> bool:
    """Ask through an isolated Tk child; safe when called from a worker thread."""
    if cancel_event.is_set() or not isinstance(command, str) or not command or len(command) > MAX_COMMAND:
        return False

    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "termylo.approval"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False

    try:
        try:
            # No command in argv, environment, shell command strings or log output.
            # stdin is private to the short-lived approval child.
            assert proc.stdin is not None
            proc.stdin.write(command.encode("utf-8"))
            proc.stdin.close()
        except (OSError, UnicodeError, ValueError):
            return False

        deadline = time.monotonic() + APPROVAL_TIMEOUT_SECONDS + PROCESS_GRACE_SECONDS
        while proc.poll() is None:
            if cancel_event.is_set() or time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return proc.returncode == 0 and not cancel_event.is_set()
    finally:
        _stop_process(proc)


def _show_dialog(command: str) -> bool:
    """The ONLY function that creates Tk; called on approval subprocess main thread."""
    if threading.current_thread() is not threading.main_thread():
        return False

    import tkinter as tk
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    try:
        root.title("Termylo: approve PowerShell command")
        root.geometry("720x370")
        root.minsize(570, 310)
        root.attributes("-topmost", True)
        accepted = False
        closed = False

        def close(value: bool = False) -> None:
            nonlocal accepted, closed
            if closed:
                return
            accepted, closed = value, True
            root.quit()

        root.protocol("WM_DELETE_WINDOW", lambda: close(False))
        tk.Label(root, text="Approve this exact PowerShell command?", font=("Segoe UI", 13, "bold")).pack(pady=(18, 6))
        tk.Label(root, text="It will run with your Windows account permissions. Deny anything unexpected.", wraplength=650).pack(padx=12)
        box = ScrolledText(root, height=9, wrap="word", font=("Consolas", 10))
        box.insert("1.0", command)
        box.configure(state="disabled")
        box.pack(padx=18, pady=12, fill="both", expand=True)
        buttons = tk.Frame(root)
        buttons.pack(pady=(0, 16))
        tk.Button(buttons, text="DENY", width=16, command=lambda: close(False)).pack(side="left", padx=10)
        tk.Button(buttons, text="APPROVE ONCE", width=20, command=lambda: close(True)).pack(side="left", padx=10)

        root.after(APPROVAL_TIMEOUT_SECONDS * 1000, lambda: close(False))
        root.mainloop()
        return accepted
    finally:
        # Explicitly delete Tcl objects from the same interpreter/main thread.
        root.destroy()


def main() -> int:
    """Short-lived approval-process entry point; default deny on every failure."""
    if os.name != "nt" or threading.current_thread() is not threading.main_thread():
        return 1
    try:
        payload = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if not payload or len(payload) > MAX_INPUT_BYTES:
            return 1
        command = payload.decode("utf-8", errors="strict")
        if not command.strip() or len(command) > MAX_COMMAND or "\x00" in command:
            return 1
        return 0 if _show_dialog(command) else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
