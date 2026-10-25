"""Physical consent for an optional native PowerShell terminal.

Runs in a separate Python process so Tk is created and destroyed on the
same main thread. No command text or API credentials pass to this window.
"""
from __future__ import annotations

import os
import sys
import threading


def main() -> int:
    if os.name != "nt" or threading.current_thread() is not threading.main_thread():
        return 1
    import tkinter as tk

    root = tk.Tk()
    root.title("Termylo — authorize a native PowerShell session")
    root.geometry("760x325")
    root.minsize(620, 300)
    root.attributes("-topmost", True)
    root.configure(bg="#101820")

    accepted = False

    def close(value: bool = False) -> None:
        nonlocal accepted
        accepted = bool(value)
        root.quit()

    root.protocol("WM_DELETE_WINDOW", lambda: close(False))
    tk.Label(
        root, text="AUTHORIZE REAL POWERSHELL SESSION?",
        font=("Segoe UI", 15, "bold"), fg="#facc15", bg="#101820",
    ).pack(padx=20, pady=(18, 10), anchor="w")
    tk.Label(
        root,
        text=(
            "A genuine Windows PowerShell console will open on this PC.\n"
            "You can type commands directly in that console.\n"
            "ChatGPT can execute additional commands in the SAME PowerShell process "
            "without asking again while the session stays active.\n"
            "These commands run as your Windows user and can change files, "
            "install software, or access services.\n"
            "Approval lasts up to FOUR HOURS from activation, even if idle. "
            "There is no idle timeout. Close the console or explicitly revoke "
            "the session to end remote access sooner."
        ),
        bg="#101820", fg="#e5e7eb",
        font=("Segoe UI", 10), wraplength=705, justify="left",
    ).pack(padx=20, anchor="w")
    row = tk.Frame(root, bg="#101820")
    row.pack(padx=20, pady=(22, 10), anchor="w")
    tk.Button(
        row, text="DENY", command=lambda: close(False),
        font=("Segoe UI", 11, "bold"), width=14,
        bg="#334155", fg="#ffffff", pady=7,
    ).pack(side="left", padx=(0, 14))
    tk.Button(
        row, text="APPROVE SESSION", command=lambda: close(True),
        font=("Segoe UI", 11, "bold"), width=22,
        bg="#166534", fg="#ffffff", pady=7,
    ).pack(side="left")

    root.after(60_000, lambda: close(False))
    try:
        root.mainloop()
        return 0 if accepted else 1
    finally:
        root.destroy()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(1)
