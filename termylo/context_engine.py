"""Terminal Context Engine: optional, local multimodal content search.

DigUp is an external MIT-licensed search engine, not part of this package.
No voice, extra embedding model, GUI, installation, or network service is added.
Search results are candidates. File references must be verified before actions.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import secrets
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .context_assets import MODEL_ASSETS, inspect_assets
from .context_inventory import scan_roots
from .context_watcher import ContextWatcher

MAX_HITS = 12
MAX_EXCERPT = 600
MAX_HASH_ON_SEARCH = 64 * 1024 * 1024
REF_LIFETIME = 900.0
REF_LIMIT = 250
REFRESH_SECONDS = 120.0


class ContextError(RuntimeError):
    pass


@dataclass
class Reference:
    project: str
    path: Path
    device: int
    inode: int
    size: int
    mtime_ns: int
    sha256: str | None
    created: float


def _contained(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == r or r in path.parents for r in roots)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metadata(path: Path, *, full_hash: bool = False) -> tuple[dict, Reference]:
    st = path.stat()
    if not path.is_file():
        raise ContextError("Search result is not a regular file.")
    digest = _sha256(path) if full_hash or st.st_size <= MAX_HASH_ON_SEARCH else None
    if digest is not None:
        after = path.stat()
        if (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ContextError("File changed during hashing.")
    # The file ID is a locator, not a proof of unchanged content.
    fid = hashlib.sha256(
        (str(st.st_dev) + "|" + str(st.st_ino) + "|" + os.path.normcase(str(path))).encode("utf-8")
    ).hexdigest()[:24]
    meta = {
        "file_id": fid, "path": str(path), "filename": path.name,
        "bytes": st.st_size, "modified_utc":
            datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        "sha256": digest,
        "sha256_state": "computed" if digest is not None else "deferred_large_file",
    }
    ref = Reference("", path, st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns,
                    digest, time.monotonic())
    return meta, ref


class ContextProject:
    def __init__(self, key: str, directory: Path):
        self.key = key
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.config_path = directory / "config.json"
        self.index_path = directory / "digup-index"
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._messages: queue.Queue[dict] = queue.Queue()
        self._started_roots: tuple[str, ...] = ()
        self._index: subprocess.Popen | None = None
        self._index_error: str | None = None
        self._index_status = "not_started"
        self._index_last = 0.0
        self._index_job = None
        self._service_job = None
        self._lease_valid = lambda: False
        self._verified_stamp = None
        self._watcher = None
        self._config: dict = {"enabled": False, "executable": "", "roots": [],
                              "models_dir": "", "binary_sha256": ""}
        self._load()

    def _load(self):
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
            if isinstance(config, dict) and isinstance(config.get("roots"), list):
                self._config = {k: config.get(k, self._config[k]) for k in self._config}
        except (OSError, ValueError, TypeError):
            pass

    def save(self):
        tmp = self.config_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._config, indent=2), encoding="utf-8")
        tmp.replace(self.config_path)

    def roots(self) -> tuple[Path, ...]:
        result = []
        for root in self._config["roots"]:
            try:
                path = Path(root).resolve(strict=True)
                if path.is_dir():
                    result.append(path)
            except (OSError, ValueError, RuntimeError):
                continue
        return tuple(result)

    def _asset_stamp(self) -> tuple | None:
        """A cheap change detector; never substitutes for first full digest."""
        paths = [self._config.get("executable", "")]
        folder = self._config.get("models_dir", "")
        paths.extend([str(Path(folder) / name) for name, _, _ in MODEL_ASSETS]
                     if folder else ["", ""])
        result = []
        try:
            for raw in paths:
                if not raw:
                    return None
                path = Path(raw)
                if path.is_symlink():
                    return None
                st = path.stat()
                result.append((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns))
            return tuple(result)
        except (OSError, ValueError):
            return None

    def asset_check(self, *, verify_hashes: bool = True) -> dict:
        return inspect_assets(self._config.get("executable", ""),
                              self._config.get("models_dir", ""),
                              self._config.get("binary_sha256", ""),
                              verify_hashes=verify_hashes)

    def installed(self) -> bool:
        name = self._config.get("executable", "")
        return bool(name and Path(name).is_absolute() and Path(name).is_file())

    def environment(self) -> dict:
        env = dict(os.environ)
        if self._config.get("models_dir"):
            env["DIGUP_MODELS"] = self._config["models_dir"]
        return env

    def _stop_process(self, proc: subprocess.Popen | None, job) -> None:
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except OSError:
                    pass
        if job is not None:
            job.close()

    def close(self):
        with self._lock:
            if self._watcher is not None:
                self._watcher.stop()
                self._watcher = None
            if self._index_status == 'indexing':
                self._index_status = 'stopped'
            self._stop_process(self._index, self._index_job)
            self._stop_process(self._process, self._service_job)
            self._index = None
            self._process = None
            self._index_job = None
            self._service_job = None
            self._messages = queue.Queue()

    def _ensure_index_dir(self):
        if self.index_path.is_symlink() or (
            hasattr(self.index_path, "is_junction") and self.index_path.is_junction()
        ):
            raise ContextError("Refusing redirected index directory.")
        self.index_path.mkdir(parents=True, exist_ok=True)

    def _launch(self, args: list[str], *, pipes: bool = False):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(
            args, cwd=str(self.directory), env=self.environment(),
            stdin=subprocess.PIPE if pipes else subprocess.DEVNULL,
            stdout=subprocess.PIPE if pipes else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, text=pipes, encoding="utf-8" if pipes else None,
            errors="replace" if pipes else None, bufsize=1 if pipes else -1,
            creationflags=flags,
        )
        job = None
        if os.name == "nt":
            from .windows_job import attach_kill_on_close
            try:
                job = attach_kill_on_close(proc)
            except Exception:
                self._stop_process(proc, None)
                raise
        return proc, job

    @staticmethod
    def _read_messages(proc, output):
        try:
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(event, dict):
                    output.put(event)
        finally:
            output.put({"event": "eof"})

    def _await(self, request_id: str | None, seconds: float) -> dict:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                event = self._messages.get(timeout=max(0.01, end - time.monotonic()))
            except queue.Empty:
                break
            if event.get("event") == "eof":
                raise ContextError("Content search service closed unexpectedly.")
            if request_id is None and event.get("event") == "ready":
                return event
            if request_id is not None and event.get("id") == request_id:
                if event.get("ok") is False:
                    raise ContextError(str(event.get("error", "Search failed"))[:200])
                return event
        raise ContextError("Content search service timed out.")

    def _start_service(self, roots: tuple[Path, ...]):
        roots_as_text = tuple(str(r) for r in roots)
        if self._process is not None and self._process.poll() is None and roots_as_text == self._started_roots:
            return
        self._stop_process(self._process, self._service_job)
        self._process = None
        self._service_job = None
        self._messages = queue.Queue()
        self._ensure_index_dir()
        excludes = ["--exclude", str(self.directory)]
        if self._config.get("models_dir"):
            excludes += ["--exclude", self._config["models_dir"]]
        proc, job = self._launch(
            [self._config["executable"], "search-service", "--index",
             str(self.index_path), *excludes, *roots_as_text], pipes=True)
        self._process, self._service_job = proc, job
        self._started_roots = roots_as_text
        output = self._messages
        threading.Thread(target=self._read_messages, args=(proc, output),
                         daemon=True, name="termylo-context-reader").start()
        try:
            self._await(None, 12.0)
            if not self._lease_valid():
                raise ContextError("Project authorization expired during search startup.")
            threading.Thread(target=self._service_monitor, args=(proc,),
                             daemon=True, name="termylo-context-lease").start()
        except ContextError:
            self._stop_process(proc, job)
            self._process = None
            self._service_job = None
            raise

    def _service_monitor(self, proc) -> None:
        while proc.poll() is None:
            if not self._lease_valid():
                with self._lock:
                    if self._process is proc:
                        self.close()
                return
            time.sleep(.25)

    def request(self, data: dict, roots: tuple[Path, ...]) -> dict:
        with self._lock:
            try:
                self._start_service(roots)
                if not self._lease_valid():
                    raise ContextError("Project authorization expired.")
                identifier = uuid4().hex
                self._process.stdin.write(json.dumps({"id": identifier, **data}) + "\n")
                self._process.stdin.flush()
                response = self._await(identifier, 15.0)
                if not self._lease_valid():
                    raise ContextError("Project authorization expired during search.")
                return response
            except (OSError, BrokenPipeError, ValueError, ContextError) as exc:
                self._stop_process(self._process, self._service_job)
                self._process = None
                self._service_job = None
                raise ContextError(str(exc)[:240]) from exc

    def index(self, roots: tuple[Path, ...], *, grant_valid) -> dict:
        with self._lock:
            if self._index is not None and self._index.poll() is None:
                return {"status": "indexing", "already_running": True}
            if not self.installed():
                return {"status": "not_installed"}
            if not grant_valid():
                return {"status": "approval_required"}
            try:
                self._ensure_index_dir()
            except (ContextError, OSError) as exc:
                return {"status": "error", "error": str(exc)[:180]}
            excludes = ["--exclude", str(self.directory)]
            if self._config.get("models_dir"):
                excludes += ["--exclude", self._config["models_dir"]]
            args = [self._config["executable"], "index", "--index",
                    str(self.index_path), *excludes, *(str(x) for x in roots)]
            try:
                proc, job = self._launch(args)
            except OSError as exc:
                return {"status": "error", "error": str(exc)[:180]}
            self._index, self._index_job = proc, job
            self._index_status = "indexing"
            self._index_error = None
            self._index_last = time.monotonic()
            def watch():
                status = "error"
                code = None
                while proc.poll() is None:
                    if not grant_valid():
                        self._stop_process(proc, job)
                        status = "approval_expired"
                        break
                    time.sleep(.2)
                code = proc.poll()
                if status != "approval_expired":
                    status = "ready" if code == 0 else "error"
                with self._lock:
                    if self._index is proc:
                        self._index_status = status
                        self._index_error = None if status == "ready" else (
                            "Indexing ended without success." if code is None else
                            f"Indexer ended with code {code}.")
                        self._index = None
                        self._index_job = None
                        if status == "error":
                            self._index_last = 0.0  # Retry after failed indexing.
                    if job is not None:
                        job.close()
                    # The search service retains vectors until explicitly reloaded.
                    # A successful incremental index must become visible immediately.
                    if (status == "ready" and grant_valid()
                            and self._process is not None
                            and self._process.poll() is None):
                        try:
                            self.request({"op": "reload"}, roots)
                        except ContextError as exc:
                            # A failed reload closes the service in request().
                            # The next search opens a new copy of the index.
                            self._index_error = "Search refresh failed; will restart: " + str(exc)[:120]
            threading.Thread(target=watch, daemon=True,
                             name="termylo-context-index").start()
            return {"status": "indexing", "already_running": False}

    def status(self) -> dict:
        assets = self.asset_check(verify_hashes=False)
        return {
            "enabled": self._config["enabled"],
            "installed": self.installed(),
            "model_files_present": all(item["state"] == "present_unverified"
                                       for item in assets["models"]),
            "model_bytes_expected": assets["total_model_bytes"],
            "model_bytes_remaining": assets["additional_model_bytes"],
            "configured_roots": list(self._config["roots"]),
            "search_model": "upstream EmbeddingGemma 2 (external)",
            "index_directory": str(self.index_path),
            "index_status": self._index_status,
            "index_error": self._index_error,
            "service_running": self._process is not None and self._process.poll() is None,
            "watcher": self._watcher.status() if self._watcher else
                       {"active": False, "state": "off"},
        }


class TerminalContextEngine:
    def __init__(self, approval, projects, home: Path | None = None):
        self.approval = approval
        self.projects = projects
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
        self.home = Path(home) if home is not None else base / "Termylo" / "context"
        self._lock = threading.RLock()
        self._projects: dict[str, ContextProject] = {}
        self._refs: dict[str, Reference] = {}
        self._grant_ids: dict[str, str] = {}

    def _project(self, project_id: str):
        key, shell = self.projects.get(project_id)
        with self._lock:
            if key not in self._projects:
                name = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
                self._projects[key] = ContextProject(key, self.home / name)
            return key, shell, self._projects[key]

    def _authorize(self, project_id: str):
        key, shell, project = self._project(project_id)
        grant = self.approval.status()
        if (grant.get("status") != "active" or
            not grant.get("grant_id") or grant.get("remaining_seconds", 0) <= 0 or
            shell.status().get("status") != "active"):
            project.close()
            self._grant_ids.pop(key, None)
            return key, project, {"status": "approval_required",
                                   "error": "Active locally approved project terminal required."}
        old = self._grant_ids.get(key)
        if old and old != grant["grant_id"]:
            project.close()
        self._grant_ids[key] = grant["grant_id"]
        return key, project, None

    def configure(self, project_id: str, executable: str, roots: list[str],
                  *, models_dir: str = "", enabled: bool = False,
                  binary_sha256: str = "") -> dict:
        key, project, failure = self._authorize(project_id)
        if failure:
            return failure
        if enabled is not False:
            return {"status": "rejected", "error":
                    "Configuration never activates the optional engine. Use context_enable."}
        if binary_sha256 and (not isinstance(binary_sha256, str) or
                              len(binary_sha256) != 64 or
                              any(x not in "0123456789abcdef"
                                  for x in binary_sha256.lower())):
            return {"status": "rejected", "error": "Expected executable SHA-256 must be 64 hex digits."}
        if not isinstance(roots, list) or not roots or len(roots) > 20:
            return {"status": "rejected", "error": "Select 1 to 20 search folders."}
        if not isinstance(executable, str) or not Path(executable).is_absolute():
            return {"status": "rejected", "error": "Use an explicit absolute CLI executable path."}
        if models_dir and not Path(models_dir).is_absolute():
            return {"status": "rejected", "error": "Model directory must be an absolute path."}
        resolved = []
        try:
            for name in roots:
                if not isinstance(name, str):
                    raise ValueError("Folder must be a path.")
                path = Path(name).resolve(strict=True)
                if not path.is_dir():
                    raise ValueError("Search roots must be existing directories.")
                resolved.append(str(path))
        except (OSError, ValueError, RuntimeError) as exc:
            return {"status": "rejected", "error": str(exc)[:180]}
        with project._lock:
            project.close()
            project._verified_stamp = None
            old_roots = tuple(project._config.get("roots", []))
            if old_roots and old_roots != tuple(sorted(set(resolved))):
                if project.index_path.is_symlink() or (
                    hasattr(project.index_path, "is_junction") and
                    project.index_path.is_junction()
                ):
                    return {"status": "rejected", "error": "Unsafe redirected index directory."}
                try:
                    if project.index_path.exists():
                        shutil.rmtree(project.index_path)
                except OSError as exc:
                    return {"status": "error", "error": "Cannot clear obsolete index: " + str(exc)[:120]}
                project._index_status = "not_started"
                project._index_last = 0.0
            project._config = {
                "enabled": False, "executable": str(Path(executable)),
                "roots": sorted(set(resolved)), "models_dir": models_dir,
                "binary_sha256": binary_sha256.lower()}
            project.save()
            with self._lock:
                self._refs = {token: ref for token, ref in self._refs.items()
                              if ref.project != key}
            return {"status": "configured", "project_id": key, **project.status()}

    def inventory(self, project_id: str, *, max_files: int = 10000) -> dict:
        key, project, failure = self._authorize(project_id)
        if failure:
            return failure
        roots = project.roots()
        if not roots:
            return {"status": "no_roots", "project_id": key}
        if isinstance(max_files, bool) or not isinstance(max_files, int):
            return {"status": "rejected", "error": "max_files must be an integer"}
        try:
            excludes = [self.home]
            if project._config.get("models_dir"):
                excludes.append(Path(project._config["models_dir"]))
            result = scan_roots(roots, max_files=max_files, exclude=tuple(excludes))
        except (OSError, ValueError) as exc:
            return {"status": "rejected", "error": str(exc)[:160]}
        if not self._lease_check(key, self._grant_ids[key])():
            return {"status": "approval_required"}
        return {"project_id": key, **result}

    def preflight(self, project_id: str, *, verify_hashes: bool = True) -> dict:
        key, project, failure = self._authorize(project_id)
        if failure:
            return failure
        result = project.asset_check(verify_hashes=verify_hashes)
        return {"project_id": key, **result,
                "note": "Read-only local verification; no downloads or installation."}

    def enable(self, project_id: str) -> dict:
        key, project, failure = self._authorize(project_id)
        if failure:
            return failure
        with project._lock:
            # Read the full 865 MB model hash once at explicit opt-in time.
            checked = project.asset_check(verify_hashes=True)
            if not checked["ready"]:
                return {"status": "not_ready", "project_id": key,
                        "problems": checked["problems"],
                        "additional_model_bytes": checked["additional_model_bytes"]}
            if not project.roots():
                return {"status": "no_roots", "project_id": key}
            project._config["enabled"] = True
            project._verified_stamp = project._asset_stamp()
            project.save()
            return {"status": "enabled", "project_id": key,
                    "message": "Opt-in enabled. Indexing begins only when explicitly requested or searched."}

    def disable(self, project_id: str) -> dict:
        key, project, failure = self._authorize(project_id)
        if failure:
            return failure
        with project._lock:
            project.close()
            project._config["enabled"] = False
            project._verified_stamp = None
            project.save()
            with self._lock:
                self._refs = {token: ref for token, ref in self._refs.items()
                              if ref.project != key}
        return {"status": "disabled", "project_id": key}

    def status(self, project_id: str) -> dict:
        key, project, failure = self._authorize(project_id)
        if failure:
            return failure
        return {"status": "ready", "project_id": key, **project.status()}

    def _ready(self, project_id: str):
        key, project, failure = self._authorize(project_id)
        if failure:
            return key, project, (), failure
        if not project._config["enabled"]:
            return key, project, (), {"status": "disabled"}
        if project._verified_stamp is None or project._verified_stamp != project._asset_stamp():
            checked = project.asset_check(verify_hashes=True)
            if not checked["ready"]:
                project.close()
                return key, project, (), {"status": "not_ready",
                                          "problems": checked["problems"]}
            project._verified_stamp = project._asset_stamp()
        if not project.installed():
            return key, project, (), {"status": "not_installed",
                                     "message": "Install and verify the external search CLI first."}
        roots = project.roots()
        if not roots:
            return key, project, (), {"status": "no_roots"}
        return key, project, roots, None

    def _lease_check(self, key: str, grant_id: str):
        def valid():
            try:
                current = self.approval.status()
                _, shell = self.projects.get(key)
                return (current.get("status") == "active" and
                        current.get("grant_id") == grant_id and
                        shell.status().get("status") == "active")
            except Exception:
                return False
        return valid

    def watch(self, project_id: str, *, enabled: bool = False,
              interval_seconds: int = 90) -> dict:
        key, project, failure = self._authorize(project_id)
        if failure:
            return failure
        if not enabled:
            with project._lock:
                if project._watcher is not None:
                    project._watcher.stop()
                    project._watcher = None
            return {"status": "stopped", "project_id": key,
                    "message": "No background folder watcher."}
        if (isinstance(interval_seconds, bool) or
            not isinstance(interval_seconds, int) or
            not 30 <= interval_seconds <= 3600):
            return {"status": "rejected",
                    "error": "Watcher interval must be 30..3600 seconds."}
        key, project, roots, failure = self._ready(key)
        if failure:
            return failure
        with project._lock:
            if project._watcher is not None:
                if project._watcher.status()["active"]:
                    return {"project_id": key, **project._watcher.status()}
                project._watcher.stop()
            model_folder = project._config.get("models_dir", "")
            excludes = [self.home]
            if model_folder:
                excludes.append(Path(model_folder))
            watcher = ContextWatcher(
                roots, exclude=tuple(excludes),
                interval_seconds=interval_seconds,
                allowed=self._lease_check(key, self._grant_ids[key]),
                index_changed=lambda: self.index(key),
            )
            result = watcher.start()
            if result["state"] != "watching":
                return {"status": result["state"], "project_id": key, **result}
            project._watcher = watcher
            return {"status": "watching", "project_id": key, **result}

    def index(self, project_id: str) -> dict:
        key, project, roots, failure = self._ready(project_id)
        if failure:
            return failure
        grant_id = self._grant_ids[key]
        project._lease_valid = self._lease_check(key, grant_id)
        return {"project_id": key, **project.index(
            roots, grant_valid=self._lease_check(key, grant_id))}

    def search(self, project_id: str, query: str, *,
               meaning: bool = True, limit: int = 6) -> dict:
        key, project, roots, failure = self._ready(project_id)
        if failure:
            return failure
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            return {"status": "rejected", "error": "Query must be 1 to 500 characters."}
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > MAX_HITS:
            return {"status": "rejected", "error": "limit must be 1 to 12."}
        grant_id = self._grant_ids[key]
        project._lease_valid = self._lease_check(key, grant_id)
        # Re-index on demand; upstream is responsible for incremental updates.
        if (project._index is None and
            time.monotonic() - project._index_last >= REFRESH_SECONDS):
            try:
                project.index(roots, grant_valid=self._lease_check(key, grant_id))
            except (ContextError, OSError) as exc:
                return {"status": "error", "error": str(exc)[:180]}
        try:
            response = project.request(
                {"op": "search", "q": query, "meaning": bool(meaning),
                 "prefix_last": not meaning, "limit": limit}, roots)
        except ContextError as exc:
            return {"status": "error", "error": str(exc), "project_id": key}
        if not project._lease_valid():
            project.close()
            return {"status": "approval_required"}
        raw_hits = response.get("hits", [])
        if not isinstance(raw_hits, list):
            return {"status": "error", "error": "Malformed search results."}
        found = []
        for hit in raw_hits[:limit * 3]:
            if not isinstance(hit, dict) or not isinstance(hit.get("path"), str):
                continue
            try:
                real = Path(hit["path"]).resolve(strict=True)
                if not _contained(real, roots) or not real.is_file():
                    continue
                metadata, ref = _metadata(real)
                ref.project = key
                token = secrets.token_urlsafe(18)
                with self._lock:
                    self._refs[token] = ref
                    self._trim_refs()
                location = hit.get("loc")
                if location is not None and not isinstance(location, (int, float, str)):
                    location = None
                raw_score = hit.get("score", None)
                score = float(raw_score) if isinstance(raw_score, (int, float)) else None
                if score is not None and not math.isfinite(score):
                    score = None
                found.append({
                    "reference": token, **metadata,
                    "kind": str(hit.get("kind", ""))[:40],
                    "excerpt": str(hit.get("excerpt", ""))[:MAX_EXCERPT],
                    "location": location,
                    "location_end": hit.get("loc_end") if isinstance(hit.get("loc_end"), (int, float)) else None,
                    "score": score,
                })
                if len(found) >= limit:
                    break
            except (OSError, RuntimeError, ValueError, ContextError):
                continue
        return {"status": "ok", "project_id": key, "query": query,
                "meaning": bool(meaning), "index_status": project._index_status,
                "hits": found, "note": "Search results are read-only candidates; verify before modifying a file."}

    def _trim_refs(self):
        now = time.monotonic()
        for token, ref in tuple(self._refs.items()):
            if now - ref.created > REF_LIFETIME:
                del self._refs[token]
        if len(self._refs) > REF_LIMIT:
            for token in list(self._refs)[:len(self._refs) - REF_LIMIT]:
                del self._refs[token]

    def verify(self, project_id: str, reference: str) -> dict:
        key, project, failure = self._authorize(project_id)
        if failure:
            return failure
        with self._lock:
            self._trim_refs()
            ref = self._refs.get(reference) if isinstance(reference, str) else None
        if not project._config["enabled"]:
            return {"status": "disabled"}
        if ref is None or ref.project != key:
            return {"status": "not_found", "error": "Unknown, expired or cross-project file reference."}
        try:
            real = ref.path.resolve(strict=True)
            if not _contained(real, project.roots()) or real != ref.path:
                return {"status": "stale", "error": "File moved or left approved folders."}
            metadata, current = _metadata(real, full_hash=True)
            if ((ref.device, ref.inode, ref.size, ref.mtime_ns) !=
                (current.device, current.inode, current.size, current.mtime_ns) or
                (ref.sha256 is not None and ref.sha256 != current.sha256)):
                return {"status": "stale", "error": "File changed; search again."}
            if not self._lease_check(key, self._grant_ids.get(key, ""))():
                project.close()
                return {"status": "approval_required"}
            return {"status": "verified", "project_id": key,
                    "reference": reference, **metadata}
        except (OSError, RuntimeError, ValueError, ContextError):
            return {"status": "stale", "error": "File unavailable; search again."}

    def close(self):
        with self._lock:
            for project in self._projects.values():
                project.close()
            self._refs.clear()
