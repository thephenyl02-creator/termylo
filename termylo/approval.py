"""Desktop approval dialog. Denies commands when no interactive UI exists."""
from __future__ import annotations

def ask_local_user(command: str) -> bool:
    import tkinter as tk
    from tkinter.scrolledtext import ScrolledText
    root = tk.Tk()
    root.title("Termylo — PowerShell command approval")
    root.geometry("680x330")
    root.minsize(540, 280)
    root.attributes("-topmost", True)
    approved = {"value": False}
    def finish(value: bool) -> None:
        approved["value"] = value
        root.quit()
    root.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    tk.Label(root, text="Approve this command on YOUR laptop?", font=("Segoe UI", 13, "bold")).pack(padx=16, pady=(16, 5))
    tk.Label(root, text="PowerShell can read, change or delete files. Deny unexpected commands.", wraplength=635).pack(padx=16, pady=5)
    box = ScrolledText(root, height=7, wrap="word", font=("Consolas", 10))
    box.insert("1.0", command)
    box.configure(state="disabled")
    box.pack(fill="both", expand=True, padx=16, pady=8)
    buttons = tk.Frame(root)
    buttons.pack(pady=(0, 12))
    tk.Button(buttons, text="DENY", width=14, command=lambda: finish(False)).pack(side="left", padx=10)
    tk.Button(buttons, text="APPROVE ONCE", width=18, command=lambda: finish(True)).pack(side="left", padx=10)
    root.after(60_000, lambda: finish(False))
    try:
        root.mainloop()
        return approved["value"]
    finally:
        root.destroy()
