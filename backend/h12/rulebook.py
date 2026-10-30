"""rules/ 디렉터리의 YAML 규칙 파일을 읽는다.

기본 위치는 저장소 루트의 rules/ 이고, H12_RULES_DIR 환경 변수로 바꿀 수 있다.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from h12.domain.reference import AnalysisType, OptionList, parse_analysis_types, parse_options
from h12.domain.workflow import WorkflowRules

DEFAULT_RULES_DIR = Path(__file__).resolve().parents[2] / "rules"


def rules_dir() -> Path:
    return Path(os.environ.get("H12_RULES_DIR", DEFAULT_RULES_DIR))


def load_yaml(name: str, directory: Path | None = None) -> Any:
    path = (directory or rules_dir()) / name
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=None)
def load_workflow_rules(directory: Path | None = None) -> WorkflowRules:
    return WorkflowRules.from_dicts(
        load_yaml("workflow.yaml", directory),
        load_yaml("reason_codes.yaml", directory),
    )


@lru_cache(maxsize=None)
def load_analysis_types(directory: Path | None = None) -> dict[str, AnalysisType]:
    return parse_analysis_types(load_yaml("analysis_types.yaml", directory))


@lru_cache(maxsize=None)
def load_options(directory: Path | None = None) -> dict[str, OptionList]:
    return parse_options(load_yaml("options.yaml", directory))
