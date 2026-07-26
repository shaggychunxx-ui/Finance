"""Run pipeline work in hard-killable OS processes (Windows-safe).

Critical bug fixed: never block forever on stdout.readline() — that prevented
the pipeline timeout from ever firing when a child hung without printing.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

# Last isolated pipeline / agent child PID (service watchdog reads this).
LAST_PIPELINE_CHILD_PID: int = 0
# All currently running agent/pipeline children (for multi-lane watchdog kill).
ACTIVE_CHILD_PIDS: set[int] = set()


def _kill_process_tree(pid: int) -> None:
    """Force-kill pid and all descendants (required on Windows)."""
    if pid <= 0:
        return
    try:
        if os.name == "nt":
            kwargs: dict[str, Any] = {
                "capture_output": True,
                "timeout": 20,
                "check": False,
                "creationflags": 0x08000000,  # CREATE_NO_WINDOW — no flash
            }
            try:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0
                kwargs["startupinfo"] = si
            except Exception:
                pass
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                **kwargs,
            )
        else:
            import signal

            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
    except Exception:
        pass


def _popen_kwargs() -> dict[str, Any]:
    """Isolate children; never show a console window."""
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        # CREATE_NO_WINDOW alone is the reliable "no flash" flag for console children.
        flags = 0x08000000  # CREATE_NO_WINDOW
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
        kwargs["creationflags"] = flags
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = si
        except Exception:
            pass
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _quiet_python() -> str:
    """Use base pythonw so agent children never allocate a console."""
    try:
        from process_guard import resolve_pythonw

        return str(resolve_pythonw())
    except Exception:
        return sys.executable


def _quiet_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    try:
        from process_guard import venv_env

        env = venv_env()
    except Exception:
        env = dict(os.environ)
    if extra:
        env.update(extra)
    return env


def run_command_with_timeout(
    argv: list[str],
    *,
    cwd: Path,
    timeout_sec: int,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run argv; on timeout kill the whole process tree.

    stdout/stderr go to DEVNULL (not PIPEs). Full PIPE buffers were a real
    hang mode: child fills the pipe, parent waits in communicate, timeouts
    get unreliable, and the service looks "stuck" until it dies.
    Success is judged by return code (+ caller checks output files).
    """
    timeout_sec = max(5, int(timeout_sec))
    run_env = _quiet_env(env)
    global LAST_PIPELINE_CHILD_PID
    try:
        popen_kw = _popen_kwargs()
        # Prefer DEVNULL I/O (no pipe deadlocks). _popen_kwargs may set stdin.
        popen_kw["stdout"] = subprocess.DEVNULL
        popen_kw["stderr"] = subprocess.DEVNULL
        popen_kw.setdefault("stdin", subprocess.DEVNULL)
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=run_env,
            **popen_kw,
        )
    except OSError as exc:
        return {
            "ok": False,
            "error": f"spawn failed: {exc}",
            "returncode": None,
            "stderr": "",
            "stdout": "",
            "timed_out": False,
        }

    # Expose live agent PID so the service watchdog can kill hung children.
    child_pid = int(proc.pid or 0)
    if child_pid > 0:
        LAST_PIPELINE_CHILD_PID = child_pid
        ACTIVE_CHILD_PIDS.add(child_pid)

    timed_out = False
    try:
        proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(proc.pid)
        try:
            proc.wait(timeout=8)
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
    finally:
        if child_pid:
            ACTIVE_CHILD_PIDS.discard(child_pid)
            if LAST_PIPELINE_CHILD_PID == child_pid:
                LAST_PIPELINE_CHILD_PID = 0

    if timed_out:
        return {
            "ok": False,
            "error": f"timed out after {timeout_sec}s (process tree killed)",
            "returncode": None,
            "stderr": "",
            "stdout": "",
            "timed_out": True,
        }

    return {
        "ok": proc.returncode == 0,
        "error": "" if proc.returncode == 0 else f"exit {proc.returncode}",
        "returncode": proc.returncode,
        "stderr": "",
        "stdout": "",
        "timed_out": False,
    }


def run_agent_subprocess(
    agent_id: str,
    output_path: Path,
    *,
    root: Path,
    timeout_sec: int = 75,
) -> dict[str, Any]:
    """Execute RUNNERS[agent_id] in a child process; kill tree on timeout."""
    aid = str(agent_id or "").strip()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    root = Path(root)

    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        "from pathlib import Path\n"
        "from finance_runners import load_finance_runners\n"
        f"aid = {aid!r}\n"
        f"out = Path({str(out)!r})\n"
        "runners = load_finance_runners(reload=False)\n"
        "runner = runners.get(aid) or runners.get(aid.replace('-', '_'))\n"
        "if runner is None:\n"
        "    raise SystemExit(f'no runner for {aid}')\n"
        "try:\n"
        "    from agents.pipeline_memory import invoke_agent_runner\n"
        "    invoke_agent_runner(runner, agent_id=aid, output=out)\n"
        "except Exception:\n"
        "    runner(output=out)\n"
        "if not out.exists():\n"
        "    raise SystemExit('no output written')\n"
        "print('AGENT_OK', aid)\n"
    )

    script_path: Path | None = None
    try:
        import tempfile

        out.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = root / "output" / "_agent_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f"agent_{aid}_", suffix=".py", dir=str(tmp_dir))
        os.close(fd)
        script_path = Path(tmp)
        script_path.write_text(code, encoding="utf-8")
        argv = [_quiet_python(), str(script_path)]
    except Exception:
        argv = [_quiet_python(), "-u", "-c", code]

    try:
        result = run_command_with_timeout(
            argv,
            cwd=root,
            timeout_sec=timeout_sec,
        )
    finally:
        if script_path is not None:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

    if result.get("timed_out"):
        return result
    if result.get("returncode") == 0 and not out.exists():
        result["ok"] = False
        result["error"] = "agent exited 0 but wrote no output file"
        return result
    if result.get("returncode") not in (0, None) and result.get("returncode") != 0:
        err = (result.get("stderr") or "").strip().splitlines()
        result["error"] = (err[-1] if err else result.get("error") or "agent failed")[:300]
        result["ok"] = False
    elif result.get("returncode") == 0:
        result["ok"] = out.exists()
        result["error"] = "" if result["ok"] else "no output file"
    return result


def run_pipeline_subprocess(
    *,
    root: Path,
    timeout_sec: int = 1200,
    benchmark_profile: str = "skip",
    on_line: Callable[[str], None] | None = None,
    stall_sec: int = 100,
    pipeline_id: str | None = None,
    agents_only: bool = False,
    agent_timeout_sec: int | None = None,
    split_pipelines: bool = False,
    only_lanes: list[str] | None = None,
    parallel_lanes: bool = False,
    agent_subprocess: bool = True,
) -> dict[str, Any]:
    """Run full or lane pipeline in a child process with non-blocking progress streaming.

    Timeouts:
      - overall timeout_sec for the whole cycle
      - stall_sec with no new stdout line → kill (stuck agent that never prints)

    The parent service process stays alive even if this child is OOM-killed.
    """
    root = Path(root)
    agent_sub = "1" if agent_subprocess else "0"
    lanes_repr = repr(list(only_lanes) if only_lanes else None)
    if split_pipelines:
        code = (
            "import os, sys\n"
            f"sys.path.insert(0, {str(root)!r})\n"
            f"os.environ['FINANCE_AGENT_SUBPROCESS'] = {agent_sub!r}\n"
            "os.environ['FINANCE_PREDICTOR_FETCH_PRICES'] = "
            f"{os.environ.get('FINANCE_PREDICTOR_FETCH_PRICES', '0')!r}\n"
            "os.environ['PYTHONIOENCODING'] = 'utf-8'\n"
            "os.environ['PYTHONUNBUFFERED'] = '1'\n"
            "from strategy_engine import run_split_pipelines\n"
            f"profile = {benchmark_profile!r}\n"
            f"only_lanes = {lanes_repr}\n"
            f"parallel_lanes = {bool(parallel_lanes)!r}\n"
            "def _prog(msg):\n"
            "    try:\n"
            "        print(str(msg).encode('ascii','replace').decode('ascii'), flush=True)\n"
            "    except Exception:\n"
            "        pass\n"
            "ok = run_split_pipelines(\n"
            "    on_progress=_prog,\n"
            "    check_remote=False,\n"
            "    reload_runners=False,\n"
            "    benchmark_profile=profile,\n"
            "    parallel_lanes=parallel_lanes,\n"
            "    only_lanes=only_lanes,\n"
            ")\n"
            "print('PIPELINE_OK', ok, flush=True)\n"
        )
    else:
        # Lane workers: also in-process agents (quiet). Full single-pipeline still quiet.
        agent_sub = "0" if agents_only else "0"
        code = (
            "import os, sys\n"
            f"sys.path.insert(0, {str(root)!r})\n"
            f"os.environ['FINANCE_AGENT_SUBPROCESS'] = {agent_sub!r}\n"
            "os.environ['PYTHONIOENCODING'] = 'utf-8'\n"
            "from strategy_engine import run_agent_pipeline\n"
            f"profile = {benchmark_profile!r}\n"
            f"pipeline_id = {pipeline_id!r}\n"
            f"agents_only = {bool(agents_only)!r}\n"
            f"agent_timeout_sec = {agent_timeout_sec!r}\n"
            "def _prog(msg):\n"
            "    try:\n"
            "        print(str(msg).encode('ascii','replace').decode('ascii'), flush=True)\n"
            "    except Exception:\n"
            "        pass\n"
            "ok = run_agent_pipeline(\n"
            "    on_progress=_prog,\n"
            "    check_remote=False,\n"
            "    reload_runners=False,\n"
            "    benchmark_profile=profile,\n"
            "    pipeline_id=pipeline_id,\n"
            "    agents_only=agents_only,\n"
            "    agent_timeout_sec=agent_timeout_sec,\n"
            ")\n"
            "print('PIPELINE_OK', ok, flush=True)\n"
        )
    timeout_sec = max(120, int(timeout_sec))
    stall_sec = max(45, int(stall_sec))

    # Temp script avoids python -c console flashes on Windows.
    script_path: Path | None = None
    try:
        import tempfile

        tmp_dir = root / "output" / "_agent_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="pipeline_", suffix=".py", dir=str(tmp_dir))
        os.close(fd)
        script_path = Path(tmp)
        script_path.write_text(code, encoding="utf-8")
        argv = [_quiet_python(), str(script_path)]
    except Exception:
        argv = [_quiet_python(), "-u", "-c", code]

    global LAST_PIPELINE_CHILD_PID
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_quiet_env(),
            **_popen_kwargs(),
        )
    except OSError as exc:
        if script_path is not None:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass
        return {
            "ok": False,
            "error": f"spawn failed: {exc}",
            "returncode": None,
            "stderr": "",
            "stdout": "",
            "timed_out": False,
        }

    LAST_PIPELINE_CHILD_PID = int(proc.pid or 0)

    stdout_lines: list[str] = []
    stderr_chunks: list[str] = []
    line_q: queue.Queue[str | None] = queue.Queue()
    start = time.monotonic()
    last_line_at = start

    def _reader() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line_q.put(line.rstrip("\n"))
        except Exception:
            pass
        finally:
            line_q.put(None)

    def _err_reader() -> None:
        try:
            if proc.stderr is None:
                return
            for chunk in proc.stderr:
                stderr_chunks.append(chunk)
        except Exception:
            pass

    threading.Thread(target=_reader, daemon=True).start()
    threading.Thread(target=_err_reader, daemon=True).start()

    timed_out = False
    stall_killed = False
    try:
        while True:
            now = time.monotonic()
            if now - start > timeout_sec:
                timed_out = True
                _kill_process_tree(proc.pid)
                break
            if now - last_line_at > stall_sec:
                # Child alive but silent → hung agent / deadlock
                stall_killed = True
                timed_out = True
                _kill_process_tree(proc.pid)
                break
            try:
                item = line_q.get(timeout=0.4)
            except queue.Empty:
                if proc.poll() is not None:
                    # Drain remaining
                    while True:
                        try:
                            item = line_q.get_nowait()
                        except queue.Empty:
                            item = None
                        if item is None:
                            break
                        stdout_lines.append(item)
                        last_line_at = time.monotonic()
                        if on_line is not None:
                            try:
                                on_line(item)
                            except Exception:
                                pass
                    break
                continue

            if item is None:
                break
            stdout_lines.append(item)
            last_line_at = time.monotonic()
            if on_line is not None:
                try:
                    on_line(item)
                except Exception:
                    pass
    finally:
        try:
            proc.wait(timeout=8)
        except Exception:
            _kill_process_tree(proc.pid)
        if script_path is not None:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

    stderr = "".join(stderr_chunks)
    stdout = "\n".join(stdout_lines)
    if timed_out:
        reason = "stall" if stall_killed else "overall"
        return {
            "ok": False,
            "error": (
                f"timed out after {timeout_sec}s ({reason}; process tree killed)"
                if not stall_killed
                else f"stalled {stall_sec}s with no progress (process tree killed)"
            ),
            "returncode": None,
            "stderr": stderr[-1200:],
            "stdout": stdout[-8000:],
            "timed_out": True,
        }
    return {
        "ok": proc.returncode == 0,
        "error": "" if proc.returncode == 0 else f"exit {proc.returncode}",
        "returncode": proc.returncode,
        "stderr": stderr[-1200:],
        "stdout": stdout[-8000:],
        "timed_out": False,
    }
