"""Run untrusted Python (model-generated code + tests) in a separate, limited process.

Limits applied here:
* a fresh temporary working directory, deleted afterwards
* isolated interpreter (``-I``: no user site-packages, no PYTHON* env vars)
* a stripped environment (no inherited secrets or proxy settings)
* a wall-clock timeout (the process is killed when it expires)

Not enforced here: memory caps, filesystem write restrictions outside the temp
directory, or network isolation. Those need OS-level sandboxing (a Job object
on Windows, or a container), which is planned for the app's code-runner tool.
The benchmark only executes answers to fixed, benign tasks, which is
why this lighter isolation is acceptable for evaluation.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunResult:
    passed: bool
    timed_out: bool
    output: str


def run_python(code: str, timeout: float = 10.0) -> RunResult:
    with tempfile.TemporaryDirectory(prefix="edulite_sandbox_") as workdir:
        script = Path(workdir) / "program.py"
        script.write_text(code, encoding="utf-8")
        env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
               "PYTHONIOENCODING": "utf-8"}
        try:
            proc = subprocess.run([sys.executable, "-I", str(script)], cwd=workdir, env=env,
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return RunResult(passed=False, timed_out=True, output="timeout")
        return RunResult(passed=proc.returncode == 0, timed_out=False,
                         output=(proc.stdout + proc.stderr)[-2000:])
