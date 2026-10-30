"""원본 xlsx 에서 기준 데이터 버전 파일을 만든다 — 업무정의서 9장.

    .venv/Scripts/python -m pip install -e ".[convert]"
    .venv/Scripts/python -m h12.reference.build 2026-10-30

refdata/sources/*.yaml 의 변환 규칙을 원본에 적용해 refdata/<데이터셋>/<버전>.json 을 쓴다.
버전 파일은 한번 만들면 고치지 않는다. 같은 버전에 다른 내용을 쓰려 하면 멈춘다.
새 버전을 릴리스에 넣는 것(refdata/manifest.yaml)은 사람이 한다.

변환 함수(build_taxonomy 등)는 원본 행만 받으므로 xlsx 없이 테스트할 수 있다.
openpyxl 은 이 모듈에서만, 파일을 읽을 때만 쓴다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import warnings
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from h12.domain.reference import ReferenceDataError

from .store import DATASETS, refdata_dir, version_path

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILT_DATASETS = ("taxonomy", "hx_catalog", "pms")  # measurement_standards 는 사람이 쓴다
VERSION_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}(\.\d+)?$")

Row = tuple[int, Sequence[Any]]  # (원본 행 번호, 값)
PATH_KEYS = ("division", "product_lineup", "platform", "chassis")


class BuildError(Exception):
    pass


# ---------------------------------------------------------------- 제품 분류 (4.2)

def build_taxonomy(rows: Iterable[Row], rules: Mapping[str, Any]) -> dict[str, Any]:
    modes = rules["platform_mode"]
    fixes = rules.get("fix_values") or {}
    na_real = set(rules.get("na_chassis_platforms") or [])
    exclude = rules.get("exclude") or []
    used_fixes: set[str] = set()
    used_excludes: set[int] = set()
    excluded: list[dict[str, Any]] = []
    kept: list[tuple[int, list[str], dict[str, Any]]] = []

    for row_no, values in rows:
        cells = [_text(v) for v in list(values)[:4]] + [""] * (4 - len(values[:4]))
        if not any(cells):
            continue
        used_fixes.update(c for c in cells if c in fixes)
        division, l1, l2, l3 = (fixes.get(c, c) for c in cells)
        path = _map_columns(modes.get(division), division, l1, l2, l3)
        rule = next((i for i, r in enumerate(exclude) if _matches(path, r["match"])), None)
        if rule is not None:
            used_excludes.add(rule)
            excluded.append({"row": row_no, "values": cells, "reason": exclude[rule]["reason"]})
            continue
        if modes.get(division) not in ("select", "from_lineup"):
            raise BuildError(f"{row_no}행: 사업부 {division!r} 를 읽는 규칙(platform_mode)이 없다")
        kept.append((row_no, cells, path))

    _unused("fix_values", [k for k in fixes if k not in used_fixes])
    _unused("exclude", [r["match"] for i, r in enumerate(exclude) if i not in used_excludes])

    # "NA" 는 지정한 Platform 에서만 실제 Chassis 값이다. 그 밖에서는 Chassis 없음이고,
    # 같은 Platform 에 다른 Chassis 가 있으면 그 NA 행은 뺀다
    has_chassis = {_group(p) for _, _, p in kept if p["chassis"] not in (None, "NA")}
    paths: dict[tuple, dict[str, Any]] = {}
    for row_no, cells, path in kept:
        if path["chassis"] == "NA" and path["platform"] not in na_real:
            if _group(path) in has_chassis:
                excluded.append({"row": row_no, "values": cells,
                                 "reason": "같은 Platform 에 다른 Chassis 가 있는 NA 행"})
                continue
            path = {**path, "chassis": None}
        key = tuple(path[k] for k in PATH_KEYS)
        paths.setdefault(key, {**path, "source_rows": []})["source_rows"].append(row_no)

    for item in rules.get("add") or []:
        raw = item["path"]
        mode = modes.get(raw["division"])
        platform = {"none": None, "from_lineup": raw["product_lineup"]}.get(mode, raw.get("platform"))
        path = {"division": raw["division"], "product_lineup": raw["product_lineup"],
                "platform": platform, "chassis": raw.get("chassis")}
        key = tuple(path[k] for k in PATH_KEYS)
        if key in paths:
            raise BuildError(f"추가하려는 분류 {key} 는 원본에 이미 있다")
        paths[key] = {**path, "source_rows": [], "note": item["reason"]}

    return {
        "platform_mode": dict(modes),
        "paths": [{"id": _id("PT", key), **entry} for key, entry in paths.items()],
        "excluded": sorted(excluded, key=lambda e: e["row"]),
    }


def _map_columns(mode: str | None, division: str, l1: str, l2: str, l3: str) -> dict[str, Any]:
    if mode == "from_lineup":
        # LEVEL3 은 정의서에 없는 단계라 버린다
        return {"division": division, "product_lineup": l1, "platform": l1, "chassis": l2 or None}
    return {"division": division, "product_lineup": l1, "platform": l2 or None, "chassis": l3 or None}


def _group(path: Mapping[str, Any]) -> tuple:
    return path["division"], path["product_lineup"], path["platform"]


def _matches(path: Mapping[str, Any], match: Mapping[str, Any]) -> bool:
    return all(path.get(k) == v for k, v in match.items())


# ---------------------------------------------------------------- 열교환기 Catalog (5.3.4)

HX_KEYS = {"tube_diameter", "fin_type", "row_count", "fpi", "standard"}


def build_hx_catalog(header: Sequence[Any], rows: Iterable[Row], rules: Mapping[str, Any]) -> dict[str, Any]:
    columns = rules["columns"]
    if set(columns.values()) != HX_KEYS:
        raise BuildError(f"hx_catalog columns 의 저장 키는 {sorted(HX_KEYS)} 이어야 한다")
    index = _column_index(header, columns)
    marks = rules["standard_marks"]
    spec_keys = ("tube_diameter", "fin_type", "row_count", "fpi")

    entries, seen = [], set()
    for row_no, values in rows:
        if not _text(values[index["fin_type"]]):
            break  # 사양 표가 끝났다
        entry = {k: _value_text(values[index[k]]) for k in spec_keys}
        spec = tuple(entry[k] for k in spec_keys)
        if not all(spec):
            raise BuildError(f"{row_no}행: 사양 값이 비어 있다 {spec}")
        if spec in seen:
            raise BuildError(f"{row_no}행: 같은 사양이 이미 있다 {spec}")
        mark = _text(values[index["standard"]])
        if mark not in marks:
            raise BuildError(f"{row_no}행: 표준 여부 {mark!r} 는 {list(marks)} 중 하나여야 한다")
        seen.add(spec)
        entries.append({"id": _id("HX", spec), **entry, "standard": marks[mark], "source_row": row_no})
    return {"entries": entries}


# ---------------------------------------------------------------- PMS 프로젝트 (4.4)

def build_pms(sheets: Iterable[tuple[Mapping[str, Any], Sequence[Any], Iterable[Row]]],
              rules: Mapping[str, Any]) -> dict[str, Any]:
    """sheets: (파일 규칙, 머리글, 행) 목록. 파일 규칙은 sources/pms.yaml 의 files 항목이다."""
    columns = rules["columns"]
    if not {"code", "project", "rep_model"} <= set(columns.values()):
        raise BuildError("pms columns 에 code, project, rep_model 이 있어야 한다")
    projects, codes = [], set()
    for file_rule, header, rows in sheets:
        index = _column_index(header, {**columns, rules["division_column"]: "_division"})
        for row_no, values in rows:
            cells = {k: _text(values[i]) for k, i in index.items()}
            if not any(cells.values()):
                continue
            where = f"{file_rule['file']} {row_no}행"
            if cells.pop("_division") != file_rule["pms_division"]:
                raise BuildError(f"{where}: 사업부가 {file_rule['pms_division']} 이 아니다")
            if cells["code"] in codes:
                raise BuildError(f"{where}: PMS Project Code {cells['code']} 가 중복된다")
            codes.add(cells["code"])
            projects.append({"code": cells.pop("code"), "division": file_rule["division"], **cells})
    return {"projects": projects}


# ---------------------------------------------------------------- 공통

def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _value_text(value: Any) -> str:
    """사양 값을 원본 표기대로 문자열로 만든다. 7 → "7", 9.52 → "9.52"."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:g}"
    return _text(value)


def _column_index(header: Sequence[Any], columns: Mapping[str, str]) -> dict[str, int]:
    names = [_text(h) for h in header]
    index = {}
    for name, key in columns.items():
        positions = [i for i, n in enumerate(names) if n == name]
        if len(positions) != 1:
            raise BuildError(f"원본 머리글에서 {name!r} 를 하나로 찾을 수 없다")
        index[key] = positions[0]
    return index


def _id(prefix: str, key: Iterable[Any]) -> str:
    """내용으로 만든 ID. 같은 분류·사양은 버전이 바뀌어도 ID 가 같다."""
    text = "\x1f".join("" if k is None else str(k) for k in key)
    return f"{prefix}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12].upper()}"


def _unused(name: str, items: list[Any]) -> None:
    if items:
        raise BuildError(f"{name} 규칙이 원본의 어느 행에도 맞지 않는다 (원본이 바뀌었나?): {items}")


def dumps(doc: Mapping[str, Any]) -> str:
    """목록 항목을 한 줄씩 쓰는 JSON. 버전끼리 비교할 때 항목 단위로 차이가 보인다."""
    lines = ["{"]
    for i, (key, value) in enumerate(doc.items()):
        comma = "," if i < len(doc) - 1 else ""
        if isinstance(value, list):
            lines.append(f"  {json.dumps(key)}: [")
            lines += [f"    {json.dumps(v, ensure_ascii=False)}{',' if j < len(value) - 1 else ''}"
                      for j, v in enumerate(value)]
            lines.append(f"  ]{comma}")
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_version(root: Path, dataset: str, version: str, data: Mapping[str, Any]) -> tuple[Path, bool]:
    """버전 파일을 쓴다. (경로, 새로 썼는지). 같은 버전 파일이 다른 내용으로 있으면 멈춘다."""
    if not VERSION_PATTERN.match(version):
        raise BuildError(f"버전 {version!r} 는 YYYY-MM-DD 또는 YYYY-MM-DD.N 이다")
    doc = {"dataset": dataset, "version": version, **data}
    try:
        DATASETS[dataset][1](doc)  # 업무 규칙에 맞지 않는 데이터는 쓰지 않는다
    except ReferenceDataError as e:
        raise BuildError(f"{dataset}: {e}") from None
    text = dumps(doc)
    path = version_path(root, dataset, version)
    if path.exists():
        if path.read_text(encoding="utf-8") == text:
            return path, False
        raise BuildError(f"{path} 가 이미 다른 내용으로 있다. 버전 파일은 고치지 않는다. 새 버전으로 만든다")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path, True


# ---------------------------------------------------------------- 원본 읽기

def read_rows(path: Path, sheet: str | None = None) -> list[tuple[Any, ...]]:
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # PMS 파일의 "no default style" 경고
        # read_only 는 시트의 크기 정보를 믿는데, PMS 파일은 그 정보가 틀려 첫 칸만 읽힌다
        wb = openpyxl.load_workbook(path, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        return list(ws.iter_rows(values_only=True))
    finally:
        wb.close()


def source_info(path: Path, rows: int) -> dict[str, Any]:
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "rows": rows}


def _numbered(rows: Sequence[Sequence[Any]], first_row: int) -> list[Row]:
    return [(first_row + i, r) for i, r in enumerate(rows[first_row - 1:])]


def load_sources(refdata: Path) -> dict[str, Any]:
    sources = {}
    for name in BUILT_DATASETS:
        with (refdata / "sources" / f"{name}.yaml").open(encoding="utf-8") as f:
            sources[name] = yaml.safe_load(f)
    return sources


def build_dataset(name: str, rules: Mapping[str, Any], source_root: Path) -> dict[str, Any]:
    src = rules["source"]
    if name == "taxonomy":
        path = source_root / src["file"]
        rows = read_rows(path)
        header = [_text(h) for h in rows[0]]
        if header[:4] != src["columns"]:
            raise BuildError(f"{path.name}: 머리글이 {src['columns']} 가 아니다: {header}")
        data = build_taxonomy(_numbered(rows, 2), rules)
        return {"source": source_info(path, len(rows) - 1), **data}
    if name == "hx_catalog":
        path = source_root / src["file"]
        rows = read_rows(path, src["sheet"])
        data = build_hx_catalog(rows[src["header_row"] - 1], _numbered(rows, src["first_data_row"]), rules)
        return {"source": {**source_info(path, len(data["entries"])), "sheet": src["sheet"]}, **data}
    if name == "pms":
        sheets, infos = [], []
        for file_rule in src["files"]:
            path = source_root / src["dir"] / file_rule["file"]
            rows = read_rows(path)
            sheets.append((file_rule, rows[0], _numbered(rows, 2)))
            infos.append(source_info(path, len(rows) - 1))
        return {"source": infos, **build_pms(sheets, rules)}
    raise BuildError(f"{name} 은 변환 대상이 아니다")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m h12.reference.build", description=__doc__.split("\n")[0])
    parser.add_argument("version", help="만들 버전 (YYYY-MM-DD 또는 YYYY-MM-DD.N)")
    parser.add_argument("--only", nargs="+", choices=BUILT_DATASETS, default=list(BUILT_DATASETS))
    parser.add_argument("--refdata", type=Path, default=refdata_dir())
    parser.add_argument("--source-root", type=Path, default=REPO_ROOT,
                        help="sources/*.yaml 의 원본 경로가 기준으로 삼는 디렉터리 (기본: 저장소 루트)")
    args = parser.parse_args(argv)

    sources = load_sources(args.refdata)
    try:
        for name in args.only:
            data = build_dataset(name, sources[name], args.source_root)
            path, written = write_version(args.refdata, name, args.version, data)
            print(f"{name}: {path} ({'새로 씀' if written else '변경 없음'})")
    except BuildError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
