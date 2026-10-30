"""계층 규칙: domain 은 프레임워크, DB, 바깥 계층을 모른다 (CLAUDE.md)."""

from __future__ import annotations

import ast
from pathlib import Path

import h12

PACKAGE = Path(h12.__file__).parent

# 계층 → import 하면 안 되는 모듈 접두사
FORBIDDEN = {
    "domain": ("flask", "sqlalchemy", "alembic", "yaml", "h12.application", "h12.infra", "h12.api",
               "h12.rulebook", "h12.reference"),
    "application": ("flask", "h12.api"),
    "reference": ("flask", "sqlalchemy", "alembic", "h12.api", "h12.application", "h12.infra"),
}


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_layer_dependencies():
    violations = []
    for layer, forbidden in FORBIDDEN.items():
        for path in (PACKAGE / layer).rglob("*.py"):
            for name in _imports(path):
                if any(name == f or name.startswith(f + ".") for f in forbidden):
                    violations.append(f"{path.relative_to(PACKAGE)} → {name}")
    assert violations == []


def test_openpyxl_only_in_converter():
    """xlsx 는 기준 데이터 변환에서만 읽는다. 런타임은 openpyxl 없이 돈다."""
    users = [path.relative_to(PACKAGE).as_posix() for path in PACKAGE.rglob("*.py")
             if any(n == "openpyxl" or n.startswith("openpyxl.") for n in _imports(path))]
    assert users == ["reference/build.py"]
