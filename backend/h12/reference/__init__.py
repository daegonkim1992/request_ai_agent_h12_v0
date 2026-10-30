"""기준 데이터 읽기와 버전 관리 (업무정의서 9장, 3.4-10). 업무 규칙은 h12.domain.reference 에 있다."""

from .store import DATASETS, ReferenceStore, default_store

__all__ = ["DATASETS", "ReferenceStore", "default_store"]
