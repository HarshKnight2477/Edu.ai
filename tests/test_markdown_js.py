"""Runs the JavaScript Markdown tests with Node so they're part of the pytest run."""

import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_markdown_renderer_js():
    files = [str(f) for f in sorted(JS_TESTS.glob("*.test.js"))]
    assert files
    result = subprocess.run(["node", "--test", *files], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
