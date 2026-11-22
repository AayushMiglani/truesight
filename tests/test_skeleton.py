import subprocess
import sys

import truesight


def test_package_imports_and_module_exits_zero():
    assert truesight.__name__ == "truesight"
    completed = subprocess.run(
        [sys.executable, "-m", "truesight"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout == "usage: python -m truesight [--mcp-url URL] ALERT\n"
