import ast
import json
from pathlib import Path

import pytest

from fetchers._base import guard_catalog_write, write_catalog_guarded
from fetchers.registry import MANIFEST_PATH

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
LIBRARY_SCRIPTS = sorted({e["script"] for e in MANIFEST["fetchers"] if e.get("group") == "library"})
_EMPTY_GUARDS = {"refuse_empty_result", "guard_catalog_write", "write_catalog_guarded"}
_DRIFT_GUARDS = {"refuse_drift_result", "guard_catalog_write", "write_catalog_guarded"}


def _called_names(source):
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def _has_drift_guard(names):
    if names & _DRIFT_GUARDS:
        return True
    return any(n.startswith("refuse_") and n.endswith("_source_drift") for n in names)


@pytest.mark.parametrize("script", LIBRARY_SCRIPTS, ids=LIBRARY_SCRIPTS)
def test_library_script_guards_its_write(script):
    source = (ROOT / script).read_text(encoding="utf-8")
    names = _called_names(source)
    assert names & _EMPTY_GUARDS, f"{script}: no empty-result guard before write"
    assert _has_drift_guard(names), f"{script}: no drift guard before write"


def test_manifest_has_library_scripts():
    assert len(LIBRARY_SCRIPTS) >= 10


def test_guard_refuses_empty(tmp_path):
    out = tmp_path / "games.json"
    assert guard_catalog_write([], label="X", output_path=out) == 2
    assert guard_catalog_write([], label="X", output_path=out, allow_empty=True) is None


def test_guard_refuses_drift(tmp_path):
    out = tmp_path / "games.json"
    out.write_text(json.dumps({"game_count": 100, "games": []}), encoding="utf-8")
    assert guard_catalog_write(10, label="X", output_path=out) == 3
    assert guard_catalog_write(10, label="X", output_path=out, allow_drift=True) is None


def test_guarded_write_skips_disk_when_refused(tmp_path):
    out = tmp_path / "games.json"
    code = write_catalog_guarded(out, "SHOULD-NOT-WRITE", count=[], label="X")
    assert code == 2
    assert not out.exists()


def test_guarded_write_persists_on_success(tmp_path):
    out = tmp_path / "games.json"
    payload = json.dumps({"game_count": 3, "games": [1, 2, 3]})
    code = write_catalog_guarded(out, payload, count=[1, 2, 3], label="X")
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["game_count"] == 3
