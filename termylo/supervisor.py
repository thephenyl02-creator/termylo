"""Restart-independent, local-only Termylo approval supervisor.

Authenticated Windows named pipe; single lease stored in RAM, never on disk.
Windows DPAPI protects the pipe authentication key. No public listener.
"""
from __future__ import annotations
import ctypes
import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
from pathlib import Path
from .universal_approval import UniversalApproval

MAX_MSG = 4096

class Unavailable(RuntimeError):
    pass

class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]

def dpapi(data: bytes, encrypt: bool) -> bytes:
    if os.name != "nt":
        raise OSError("Persistent owner approval requires Windows.")
    crypto = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    name = "CryptProtectData" if encrypt else "CryptUnprotectData"
    action = getattr(crypto, name)
    if encrypt:
        action.argtypes = [ctypes.POINTER(Blob), ctypes.c_wchar_p,
                           ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                           wintypes.DWORD, ctypes.POINTER(Blob)]
    else:
        action.argtypes = [ctypes.POINTER(Blob), ctypes.POINTER(ctypes.c_wchar_p),
                           ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                           wintypes.DWORD, ctypes.POINTER(Blob)]
    action.restype = wintypes.BOOL
    raw = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(raw, ctypes.POINTER(ctypes.c_byte)))
    result = Blob()
    label = ctypes.c_wchar_p()
    if encrypt:
        ok = action(ctypes.byref(source), "Termylo local pipe key", None,
                    None, None, 1, ctypes.byref(result))
    else:
        ok = action(ctypes.byref(source), ctypes.byref(label), None,
                    None, None, 1, ctypes.byref(result))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))
        if label:
            kernel.LocalFree(ctypes.cast(label, ctypes.c_void_p))

def home() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Termylo" / "Supervisor"

def suffix(folder=None) -> str:
    folder = folder or home()
    return hashlib.sha256(str(folder.resolve()).casefold().encode()).hexdigest()[:24]

def address(folder=None) -> str:
    return r"\\.\pipe\TermyloOwnerApproval-" + suffix(folder)

def authkey(folder=None) -> bytes:
    folder = folder or home()
    if folder.is_symlink():
        raise Unavailable("Redirected supervisor folder refused.")
    folder.mkdir(parents=True, exist_ok=True)
    keyfile = folder / "auth.dpapi"
    if keyfile.is_symlink():
        raise Unavailable("Redirected supervisor key refused.")
    if not keyfile.exists():
        ciphertext = dpapi(secrets.token_bytes(32), True)
        try:
            fd = os.open(str(keyfile), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as file:
                file.write(ciphertext)
        except FileExistsError:
            pass
    key = dpapi(keyfile.read_bytes(), False)
    if len(key) != 32:
        raise Unavailable("Invalid encrypted supervisor authentication key.")
    return key

def encode(message: dict) -> bytes:
    raw = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_MSG:
        raise Unavailable("Supervisor message size exceeded.")
    return raw

def rpc(op: str, *, start=False, folder=None, **kwargs) -> dict:
    folder = folder or home()
    if not start and not (folder / "auth.dpapi").exists():
        raise Unavailable("No supervisor is running.")
    key = authkey(folder)
    def attempt():
        link = Client(address(folder), family="AF_PIPE", authkey=key)
        try:
            link.send_bytes(encode({"op": op, **kwargs}))
            answer = json.loads(link.recv_bytes(MAX_MSG).decode("utf-8"))
            if not isinstance(answer, dict):
                raise Unavailable("Invalid supervisor response.")
            return answer
        finally:
            link.close()
    try:
        return attempt()
    except AuthenticationError as exc:
        # Wrong-key connections must not silently start a replacement broker.
        raise Unavailable("Supervisor authentication failed.") from exc
    except (OSError, ConnectionError, EOFError, ValueError):
        if not start:
            raise Unavailable("Supervisor not available.")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [sys.executable, "-m", "termylo.supervisor", "serve"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(Path(__file__).resolve().parents[1]),
        creationflags=flags, close_fds=True)
    deadline = time.monotonic() + 7
    while time.monotonic() < deadline:
        try:
            return attempt()
        except (OSError, ConnectionError, EOFError, ValueError):
            time.sleep(.1)
    raise Unavailable("Supervisor did not start.")

class Broker:
    def __init__(self, approval=None):
        self.approval = approval if approval is not None else UniversalApproval()
        self.instance = secrets.token_hex(12)
        self.stopping = threading.Event()

    def handle(self, request: dict) -> dict:
        op = request.get("op")
        if op == "ping":
            return {"status": "online", "instance": self.instance}
        if op == "status":
            return {**self.approval.status(), "supervisor_instance": self.instance}
        if op == "begin":
            return self.approval.begin(request.get("hours", 4))
        if op == "lease":
            if self.approval.status()["status"] != "active":
                return {"status": "closed"}
            lease = self.approval.wait()
            return {"status": "active", **lease} if lease else {"status": "closed"}
        if op == "valid":
            return {"valid": self.approval.valid(request.get("grant_id"))}
        if op == "revoke":
            return self.approval.revoke()
        if op == "restart":
            # Schedule in the independent supervisor, not in a worker-owned
            # process tree which would die as the tunnel is replaced.
            from .control import restart_worker
            threading.Thread(target=restart_worker, daemon=True,
                             name="termylo-supervised-restart").start()
            return {"status": "scheduled", "approval_preserved": True}
        if op == "stop":
            self.approval.revoke()
            self.stopping.set()
            return {"status": "stopped"}
        return {"status": "rejected", "error": "Unsupported operation."}

    def serve(self, pipe: str, key: bytes):
        listener = Listener(pipe, family="AF_PIPE", authkey=key)
        def handle_link(link):
            try:
                data = json.loads(link.recv_bytes(MAX_MSG).decode())
                if not isinstance(data, dict):
                    raise ValueError("Not a JSON object")
                response = self.handle(data)
                link.send_bytes(encode(response))
            except (OSError, EOFError, ValueError, TypeError):
                try:
                    link.send_bytes(encode({"status": "error"}))
                except OSError:
                    pass
            finally:
                link.close()
        try:
            while not self.stopping.is_set():
                try:
                    link = listener.accept()
                except AuthenticationError:
                    # Reject invalid clients without killing the approved lease.
                    continue
                except (OSError, EOFError):
                    break
                threading.Thread(target=handle_link, args=(link,), daemon=True).start()
        finally:
            listener.close()

def unique_mutex():
    if os.name != "nt":
        return None
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateMutexW.restype = wintypes.HANDLE
    handle = api.CreateMutexW(None, False, "Local\\TermyloApproval_" + suffix())
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        api.CloseHandle(handle)
        raise Unavailable("Another supervisor is already running.")
    return handle

class SupervisorApproval:
    """Same API as UniversalApproval, but worker restarts cannot reset the clock."""
    def __init__(self, *, auto_start=True):
        self.auto_start = auto_start

    def _call(self, op, **kwargs):
        try:
            return rpc(op, start=self.auto_start, **kwargs)
        except (Unavailable, OSError) as error:
            return {"status": "closed", "grant_id": None,
                    "reason": str(error)[:130], "idle_limit_seconds": None}

    def status(self):
        return self._call("status")

    def begin(self, duration_hours: float = 4):
        return self._call("begin", hours=duration_hours)

    def wait(self, cancel_event=None):
        deadline = time.monotonic() + 70
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return None
            info = self.status()
            if info.get("status") == "active":
                lease = self._call("lease")
                if lease.get("status") == "active":
                    return {k: lease[k] for k in ("grant_id", "opened_at", "duration_seconds")}
                return None
            if info.get("status") != "opening":
                return None
            time.sleep(.1)
        return None

    def valid(self, grant_id):
        return bool(grant_id and self._call("valid", grant_id=grant_id).get("valid") is True)

    def revoke(self):
        return self._call("revoke")

def main():
    if sys.argv[1:] != ["serve"]:
        raise SystemExit("Usage: python -m termylo.supervisor serve")
    mutex = unique_mutex()
    try:
        Broker().serve(address(), authkey())
    finally:
        if mutex is not None:
            ctypes.WinDLL("kernel32").CloseHandle(mutex)

if __name__ == "__main__":
    main()
