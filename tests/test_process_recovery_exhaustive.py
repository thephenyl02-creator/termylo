"""Expanded Termylo recovery and managed-process regression tests."""
from __future__ import annotations
import concurrent.futures
import os
import sqlite3
import time
import pytest
from termylo.journal import JobJournal
from termylo.jobs import JobManager
from termylo.managed_processes import MAX_PER_PROJECT, MAX_RUNNING, MAX_TAIL, ManagedProcesses

class Approval:
    def __init__(self, remaining=120):
        self.active=True; self.grant="grant-1"; self.remaining=remaining
    def status(self):
        return {"status": "active" if self.active else "closed",
                "grant_id": self.grant, "remaining_seconds": self.remaining}
class Project:
    def __init__(self, directory):
        self.directory=str(directory); self.active=True
    def status(self):
        return {"status":"active" if self.active else "closed",
                "working_directory":self.directory}
class Projects:
    def __init__(self, directory):
        self.directory=directory; self.shells={}
    def get(self, name):
        key=str(name).strip().casefold()
        if key not in self.shells: self.shells[key]=Project(self.directory)
        return key, self.shells[key]
def wait_for(mgr, jid, statuses, seconds=10):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        row=mgr.status(jid)
        if row["status"] in statuses: return row
        time.sleep(.05)
    pytest.fail("Not finished: "+str(mgr.status(jid)))

def test_journal_stale_outcomes_and_persisted_results(tmp_path):
    path=tmp_path/"journal.db"
    a=JobJournal(path)
    for state in ("queued","awaiting_approval","running"):
        a.record(state,"a",state)
    a.record("ok","a","completed",exit_code=0)
    a.record("bad","b","error",exit_code=42)
    a.close()
    b=JobJournal(path)
    for state in ("queued","awaiting_approval","running"):
        row=b.get(state)
        assert row["status"]=="outcome_unknown"
        assert row["last_known_status"]==state
        assert "no automatic replay" in row["message"]
    assert b.get("ok")["status"]=="completed"
    assert b.get("bad")["exit_code"]==42
    assert all(x["project_id"]=="a" for x in b.recent("a"))
    assert b.get("missing") is None
    b.close()

def test_journal_state_timestamps_and_bounds(tmp_path):
    j=JobJournal(tmp_path/"journal.db")
    j.record("one","p","queued")
    first=j.get("one")
    j.record("one","p","running")
    j.record("one","p","completed",exit_code=7)
    last=j.get("one")
    assert last["created_at"]==first["created_at"]
    assert last["started_at"] and last["finished_at"]
    assert last["exit_code"]==7
    for i in range(1050):
        j.record("j-"+str(i),"p"+str(i%3),"completed",exit_code=0)
    with sqlite3.connect(j.path) as db:
        assert db.execute("select count(*) from jobs").fetchone()[0]<=1000
    assert len(j.recent(limit=999999))<=100
    assert all(x["project_id"]=="p1" for x in j.recent("p1"))
    j.close()

def test_journal_concurrent_updates(tmp_path):
    j=JobJournal(tmp_path/"journal.db")
    def work(i):
        key="entry"+str(i)
        j.record(key,"p"+str(i%4),"running")
        j.record(key,"p"+str(i%4),"completed",exit_code=i)
        return j.get(key)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        rows=list(pool.map(work,range(120)))
    assert all(r["status"]=="completed" for r in rows)
    assert {r["exit_code"] for r in rows}==set(range(120))
    j.close()

def test_journal_failure_does_not_break_command(monkeypatch):
    monkeypatch.setattr("termylo.jobs.os.name","nt")
    class BrokenJournal:
        def record(self,*args,**kwargs):
            raise sqlite3.OperationalError("simulated lock")
    mgr=JobManager(lambda c,t,cancel_event:{"status":"completed","exit_code":0},
                   journal=BrokenJournal())
    job=mgr.submit("Get-Date")
    until=time.monotonic()+3
    while time.monotonic()<until:
        row=mgr.result(job["job_id"])
        if row["status"]=="completed":
            assert row["exit_code"]==0
            return
        time.sleep(.01)
    pytest.fail("A broken journal blocked normal command execution")

@pytest.mark.skipif(os.name!="nt",reason="Windows required")
def test_managed_validation_and_permission(tmp_path):
    approval=Approval()
    projects=Projects(tmp_path)
    mgr=ManagedProcesses(approval,projects)
    for cmd in (""," ","x"*2001,"text\x00value"):
        assert mgr.start(cmd,"a")["status"]=="rejected"
    for t in (0,43201,True,1.5,"5"):
        assert mgr.start("Get-Date","a",t)["status"]=="rejected"
    approval.active=False
    assert mgr.start("Get-Date","a")["status"]=="unavailable"
    approval.active=True
    projects.get("a")[1].active=False
    assert mgr.start("Get-Date","a")["status"]=="unavailable"

@pytest.mark.skipif(os.name!="nt",reason="Windows required")
def test_managed_nonzero_exit_and_journal(tmp_path):
    journal=JobJournal(tmp_path/"journal.db")
    mgr=ManagedProcesses(Approval(),Projects(tmp_path),journal)
    job=mgr.start("exit 17","a",20)
    assert job["status"]=="running"
    row=wait_for(mgr,job["process_id"],{"error"})
    assert row["exit_code"]==17
    assert journal.get(job["process_id"])["status"]=="error"
    assert journal.get(job["process_id"])["exit_code"]==17
    journal.close()

@pytest.mark.skipif(os.name!="nt",reason="Windows required")
def test_managed_timeout_and_lease_rotation(tmp_path):
    a=Approval()
    m=ManagedProcesses(a,Projects(tmp_path))
    p=m.start("Start-Sleep -Seconds 15","time",1)
    assert wait_for(m,p["process_id"],{"timeout"},9)["exit_code"] is not None
    p=m.start("Start-Sleep -Seconds 15","lease",15)
    a.grant="grant-2"
    assert wait_for(m,p["process_id"],{"approval_expired"},9)["exit_code"] is not None

@pytest.mark.skipif(os.name!="nt",reason="Windows required")
def test_managed_stdout_bound_and_unicode(tmp_path):
    m=ManagedProcesses(Approval(),Projects(tmp_path))
    p=m.start("'A'*55000","large",20)
    wait_for(m,p["process_id"],{"completed"},9)
    until=time.monotonic()+2
    while time.monotonic()<until and not m.status(p["process_id"])["stdout_truncated"]:
        time.sleep(.05)
    row=m.status(p["process_id"])
    assert row["stdout_truncated"] is True
    assert len(row["stdout_tail"].encode("utf-8"))<=MAX_TAIL
    p=m.start("Write-Output 'café 東京 नमस्ते'","unicode",20)
    wait_for(m,p["process_id"],{"completed"},9)
    until=time.monotonic()+2
    while time.monotonic()<until and not m.status(p["process_id"])["stdout_tail"]:
        time.sleep(.05)
    assert "café 東京 नमस्ते" in m.status(p["process_id"])["stdout_tail"]

@pytest.mark.skipif(os.name!="nt",reason="Windows required")
def test_managed_project_quotas_and_capacity(tmp_path):
    m=ManagedProcesses(Approval(),Projects(tmp_path))
    ids=[]
    try:
        for project in ("a","b"):
            for _ in range(MAX_PER_PROJECT):
                item=m.start("Start-Sleep -Seconds 30",project,60)
                assert item["status"]=="running"
                ids.append(item["process_id"])
        assert len(ids)==MAX_RUNNING
        assert m.start("Get-Date","c",5)["status"]=="rejected"
        assert all(p["project_id"]=="a" for p in m.list("a")["processes"])
        assert len(m.list()["processes"])==MAX_RUNNING
    finally:
        m.stop_all()
        for jid in ids: wait_for(m,jid,{"cancelled"},12)

@pytest.mark.skipif(os.name!="nt",reason="Windows required")
def test_managed_runtime_clamped_to_lease(tmp_path):
    m=ManagedProcesses(Approval(remaining=14),Projects(tmp_path))
    p=m.start("Start-Sleep -Seconds 20","a",999)
    assert p["status"]=="running"
    assert 0<p["timeout_seconds"]<=12
    assert m.stop(p["process_id"])["status"]=="stopping"
    wait_for(m,p["process_id"],{"cancelled"},10)
import subprocess
import sys

@pytest.mark.parametrize("bad_store",["blocked_parent","corrupt_database"])
def test_optional_journal_failure_does_not_stop_bridge(tmp_path,bad_store):
    import os as real_os
    env=dict(real_os.environ)
    env["LOCALAPPDATA"]=str(tmp_path)
    if bad_store=="blocked_parent":
        (tmp_path/"Termylo").write_text("not a directory",encoding="utf-8")
    else:
        folder=tmp_path/"Termylo"
        folder.mkdir()
        (folder/"jobs.sqlite3").write_text("corrupted database",encoding="utf-8")
    trial=subprocess.run([sys.executable,"-c",
                          "from termylo.server import termylo_status; assert termylo_status()['online']"],
                         cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
                         env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                         text=True,timeout=15)
    assert trial.returncode==0,trial.stderr[-1200:]
def test_journal_runtime_corruption_cannot_break_queries(tmp_path):
    class BrokenHistory:
        def get(self,key):
            raise sqlite3.DatabaseError("simulated storage corruption")
        def recent(self,*args,**kwargs):
            raise sqlite3.DatabaseError("simulated storage corruption")
    history=BrokenHistory()
    manager=JobManager(journal=history)
    assert manager.result("not-in-memory")["status"]=="not_found"
    assert manager.recent()==[]
    managed=ManagedProcesses(Approval(),Projects(tmp_path),history)
    assert managed.status("not-in-memory")["status"]=="not_found"
@pytest.mark.skipif(os.name!="nt",reason="Windows required")
def test_many_fast_managed_processes_have_no_start_races(tmp_path):
    mgr=ManagedProcesses(Approval(),Projects(tmp_path))
    for n in range(24):
        p=mgr.start("Write-Output "+str(n),"quick",12)
        assert p["status"]=="running",p
        result=wait_for(mgr,p["process_id"],{"completed","error"},8)
        assert result["status"]=="completed",result
        end=time.monotonic()+1
        while time.monotonic()<end and str(n) not in mgr.status(p["process_id"])["stdout_tail"]:
            time.sleep(.02)
        assert str(n) in mgr.status(p["process_id"])["stdout_tail"]
@pytest.mark.skipif(os.name!="nt",reason="Windows required")
def test_managed_child_terminated_if_controller_crashes(tmp_path):
    import ctypes
    import subprocess
    import sys
    from ctypes import wintypes
    pidfile=tmp_path/"managed_pid.txt"
    worker=tmp_path/"crash_probe.py"
    worker.write_text(
        "from pathlib import Path\n"
        "import time\n"
        "from termylo.managed_processes import ManagedProcesses\n"
        "class A:\n"
        "    def status(self): return {'status':'active','grant_id':'g','remaining_seconds':200}\n"
        "class S:\n"
        "    def status(self): return {'status':'active','working_directory':str(Path.home())}\n"
        "class P:\n"
        "    def get(self,n): return (n,S())\n"
        "m=ManagedProcesses(A(),P())\n"
        "job=m.start('Start-Sleep -Seconds 40','probe',40)\n"
        "assert job['status']=='running',job\n"
        + "Path("+repr(str(pidfile))+").write_text(str(job['pid']))\n"
        + "time.sleep(45)\n",
        encoding="utf-8")
    outer=subprocess.Popen([sys.executable,str(worker)],
                           stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                           cwd=str(__import__('pathlib').Path(__file__).resolve().parents[1]))
    try:
        deadline=time.monotonic()+9
        while not pidfile.exists() and time.monotonic()<deadline and outer.poll() is None:
            time.sleep(.05)
        assert pidfile.exists(),"Controller failed to start managed process"
        childpid=int(pidfile.read_text())
        outer.kill()
        outer.wait(timeout=6)
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.WaitForSingleObject.restype=wintypes.DWORD
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        kernel.CloseHandle.restype=wintypes.BOOL
        handle=kernel.OpenProcess(0x00100000,False,childpid)
        if handle:
            try:
                assert kernel.WaitForSingleObject(handle,3000)==0,(
                    "Managed PowerShell survived controller termination")
            finally:
                kernel.CloseHandle(handle)
    finally:
        if outer.poll() is None:
            outer.kill()
            outer.wait(timeout=6)

def test_persisted_journal_excludes_command_text_and_output(tmp_path,monkeypatch):
    monkeypatch.setattr("termylo.jobs.os.name","nt")
    j=JobJournal(tmp_path/"metadata.db")
    secret_command="SECRET_COMMAND_DO_NOT_STORE_789"
    secret_output="SECRET_OUTPUT_DO_NOT_STORE_123"
    manager=JobManager(lambda c,t,cancel_event:
                       {"status":"completed","exit_code":0,"stdout":secret_output},
                       journal=j)
    record=manager.submit(secret_command)
    deadline=time.monotonic()+3
    while time.monotonic()<deadline and manager.result(record["job_id"])["status"]!="completed":
        time.sleep(.01)
    assert manager.result(record["job_id"])["status"]=="completed"
    j.close()
    content=(tmp_path/"metadata.db").read_bytes()
    assert secret_command.encode() not in content
    assert secret_output.encode() not in content

@pytest.mark.skipif(os.name!="nt",reason="Windows required")
def test_managed_stderr_unicode_and_bounded_tail(tmp_path):
    m=ManagedProcesses(Approval(),Projects(tmp_path))
    p=m.start("Write-Error 'café 東京 नमस्ते'","err",20)
    wait_for(m,p["process_id"],{"error","completed"},9)
    until=time.monotonic()+2
    while time.monotonic()<until and not m.status(p["process_id"])["stderr_tail"]:
        time.sleep(.05)
    row=m.status(p["process_id"])
    assert "café 東京 नमस्ते" in row["stderr_tail"]
    p=m.start("[Console]::Error.WriteLine('E'*55000)","err",20)
    wait_for(m,p["process_id"],{"completed","error"},9)
    until=time.monotonic()+2
    while time.monotonic()<until and not m.status(p["process_id"])["stderr_truncated"]:
        time.sleep(.05)
    row=m.status(p["process_id"])
    assert row["stderr_truncated"]
    assert len(row["stderr_tail"].encode("utf-8"))<=MAX_TAIL

def test_in_memory_recent_jobs_respects_project_filter(monkeypatch):
    monkeypatch.setattr("termylo.jobs.os.name","nt")
    m=JobManager(lambda c,t,cancel_event:{"status":"completed","exit_code":0})
    a=m.submit("Get-Date",project_id="alpha")
    b=m.submit("Get-Date",project_id="beta")
    end=time.monotonic()+3
    while time.monotonic()<end and (m.result(a["job_id"])["status"]!="completed" or m.result(b["job_id"])["status"]!="completed"):
        time.sleep(.01)
    rows=m.recent("alpha")
    assert len(rows)==1
    assert rows[0]["project_id"]=="alpha"

@pytest.mark.skipif(os.name!="nt",reason="Windows required")
def test_managed_list_is_case_insensitive_for_project_keys(tmp_path):
    m=ManagedProcesses(Approval(),Projects(tmp_path))
    p=m.start("Start-Sleep -Seconds 15","Project-A",20)
    assert p["status"]=="running"
    try:
        assert any(x["process_id"]==p["process_id"] for x in m.list("PROJECT-A")["processes"])
    finally:
        m.stop_all()
        wait_for(m,p["process_id"],{"cancelled"},9)