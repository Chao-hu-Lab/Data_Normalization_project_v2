import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def test_imports_succeed_without_ms_core_checkout(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    source_pkg = project_root / "src" / "metabolomics"
    with tempfile.TemporaryDirectory() as temp_dir:
        isolated_root = Path(temp_dir)
        isolated_src = isolated_root / "src"
        shutil.copytree(source_pkg, isolated_src / "metabolomics")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(isolated_src)

        code = """
from metabolomics import utils
from metabolomics.processors import istd, qc_lowess, batch_effect, qc_batch_scaling, normalization
from metabolomics.gui.app import DataNormalizationApp

print("utils", bool(utils))
print("istd", bool(istd))
print("qc_lowess", bool(qc_lowess))
print("batch_effect", bool(batch_effect))
print("qc_batch_scaling", bool(qc_batch_scaling))
print("normalization", bool(normalization))
print("app", bool(DataNormalizationApp))
"""

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=isolated_root,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
