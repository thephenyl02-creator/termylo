"""Owner-controlled Windows desktop permission prompt. No unattended bypass."""
from __future__ import annotations
import threading

def ask_local_user(command: str, cancel_event: threading.Event) -> bool:
    import tkinter as tk
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
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

    def watch_cancel() -> None:
        if not closed and cancel_event.is_set():
            close(False)
        if not closed:
            root.after(100, watch_cancel)

    root.after(100, watch_cancel)
    root.after(60_000, lambda: close(False))
    try:
        root.mainloop()
        return accepted and not cancel_event.is_set()
    finally:
        root.destroy()
