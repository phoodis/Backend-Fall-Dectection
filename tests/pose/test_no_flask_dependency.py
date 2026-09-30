"""Guards against pose_extraction re-growing a dependency on the Flask app
package. Root cause of the original coupling: pose_extraction used to live
at app/detection/pose/, and importing ANY app.* submodule forces Python to
first execute app/__init__.py, which does top-level `import flask`,
`from flask_sqlalchemy import SQLAlchemy`, `from celery import Celery`, and
`import app.services.camera_manager` (which itself imports the DB models,
detectors, and the rest of the Flask stack). pose_extraction is now a
top-level package with zero import-time coupling to app/ - this test
proves it in a real subprocess so it's meaningful even in an environment
that happens to have Flask installed (like the bench venv, which needs
Flask for other work).
"""
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_importing_pose_factory_never_imports_flask():
    script = (
        "import sys\n"
        "import pose_extraction.factory\n"
        "print('flask' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=str(_repo_root()), timeout=30,
    )
    assert result.returncode == 0, f"import failed:\n{result.stdout}\n{result.stderr}"
    assert result.stdout.strip() == "False", (
        f"importing pose_extraction.factory pulled in flask:\n{result.stdout}\n{result.stderr}"
    )


def test_importing_pose_factory_never_imports_the_app_package():
    script = (
        "import sys\n"
        "import pose_extraction.factory\n"
        "print('app' in sys.modules or any(m.startswith('app.') for m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=str(_repo_root()), timeout=30,
    )
    assert result.returncode == 0, f"import failed:\n{result.stdout}\n{result.stderr}"
    assert result.stdout.strip() == "False", (
        f"importing pose_extraction.factory pulled in the app package:\n"
        f"{result.stdout}\n{result.stderr}"
    )
