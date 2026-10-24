"""Visible, owner-controlled terminal-style window for a Termylo session.

Runs in a separate Windows Python process. All Tk operations stay on this
process's main thread. This UI DOES NOT execute arbitrary instructions: the MCP
server owns command validation and the existing PowerShell runner.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter.scrolledtext import ScrolledText


def main() -> int:
    if os.name != "nt" or threading.current_thread() is not threading.main_thread():
        return 1

    try:
        root = tk.Tk()
    except Exception:
        return 1

    root.title("Termylo — approve visible PowerShell session")
    root.geometry("840x560")
    root.minsize(630, 420)
    root.configure(bg="#101820")
    root.attributes("-topmost", True)
    closed = False
    approved = False

    heading = tk.Label(
        root, text="TERMYLO — SESSION NOT YET APPROVED",
        fg="#facc15", bg="#101820", font=("Segoe UI", 14, "bold"),
    )
    heading.pack(padx=18, pady=(16, 8), anchor="w")

    details = tk.Label(
        root,
        text=(
            "This is a time-limited local authorization, NOT approval for just one command.\n"
            "While this window remains open, ChatGPT can run additional PowerShell commands "
            "WITHOUT asking again.\n"
            "Every command executes with your Windows account permissions. "
            "10-minute idle expiry; 30-minute maximum.\n"
            "Close this window or click REVOKE SESSION to end access immediately."
        ),
        wraplength=790, justify="left", fg="#e5e7eb", bg="#101820",
        font=("Segoe UI", 10),
    )
    details.pack(padx=18, pady=(0, 12), anchor="w")

    terminal = ScrolledText(
        root, font=("Consolas", 11), bg="#071018", fg="#c7f9cc",
        insertbackground="#ffffff", relief="flat", borderwidth=8,
        state="disabled", wrap="word",
    )
    terminal.pack(padx=18, pady=(0, 12), fill="both", expand=True)

    button_row = tk.Frame(root, bg="#101820")
    button_row.pack(pady=(0, 18))

    entries: queue.Queue[dict] = queue.Queue()
    reader_thread: threading.Thread | None = None

    def append_line(value: str) -> None:
        terminal.configure(state="normal")
        terminal.insert("end", value)
        if int(terminal.index("end-1c").split(".")[0]) > 1500:
            terminal.delete("1.0", "500.0")
        terminal.see("end")
        terminal.configure(state="disabled")

    def revoke() -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        root.destroy()

    def pump() -> None:
        if closed or not approved:
            return
        try:
            while True:
                message = entries.get_nowait()
                if message.get("type") == "disconnect":
                    revoke()
                    return
                if message.get("type") == "command":
                    append_line("\nPS> " + str(message.get("text", "")) + "\nRunning...\n")
                elif message.get("type") == "result":
                    append_line(str(message.get("text", "")) + "\n")
        except queue.Empty:
            pass
        if not closed:
            root.after(100, pump)

    def reader() -> None:
        try:
            for raw_line in sys.stdin.buffer:
                if len(raw_line) > 100_000:
                    break
                try:
                    message = json.loads(raw_line.decode("utf-8"))
                    if isinstance(message, dict) and message.get("type") in ("command", "result"):
                        entries.put(message)
                except (ValueError, UnicodeError):
                    continue
        except (OSError, ValueError):
            pass
        entries.put({"type": "disconnect"})

    def approve() -> None:
        nonlocal approved, reader_thread
        if approved or closed:
            return
        approved = True
        heading.configure(text="TERMYLO — APPROVED VISIBLE SESSION", fg="#4ade80")
        root.title("Termylo — APPROVED session (close to revoke)")
        root.attributes("-topmost", False)
        for child in button_row.winfo_children():
            child.destroy()
        tk.Button(
            button_row, text="REVOKE SESSION / CLOSE WINDOW",
            command=revoke, font=("Segoe UI", 10, "bold"),
            bg="#b91c1c", fg="#ffffff", padx=20, pady=7,
        ).pack()
        append_line(
            "Visible session approved. Commands and results appear here.\n"
            "Commands execute in isolated PowerShell processes, so variables "
            "and Set-Location do not persist between commands.\n"
            "Closing this window revokes the session.\n"
        )
        print("SESSION_APPROVED", flush=True)
        reader_thread = threading.Thread(target=reader, daemon=True, name="termylo-ui-input")
        reader_thread.start()
        root.after(100, pump)

    tk.Button(
        button_row, text="DENY", command=revoke, width=16,
        bg="#334155", fg="#ffffff", padx=10, pady=7,
    ).pack(side="left", padx=12)
    tk.Button(
        button_row, text="APPROVE SESSION", command=approve, width=24,
        bg="#166534", fg="#ffffff", padx=10, pady=7,
    ).pack(side="left", padx=12)

    root.protocol("WM_DELETE_WINDOW", revoke)
    root.after(60_000, lambda: revoke() if not approved else None)
    try:
        root.mainloop()
    finally:
        # All Tcl teardown takes place on the main thread of this child.
        if not closed:
            revoke()
    return 0 if approved else 1


if __name__ == "__main__":
    sys.exit(main())
