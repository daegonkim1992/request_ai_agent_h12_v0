"""기준 데이터의 업무 규칙 — 업무정의서 4.2, 4.4, 5.3.4, 9장, 3.4-10.

파일은 읽지 않는다. 읽기와 버전 관리는 h12.reference 가 한다.
"""

from .condition_mapping import ConditionMapping, Mark
from .errors import ReferenceDataError
from .hx_catalog import HeatExchangerType, HxCatalog, HxEntry, HxSpec, classify, is_flat_fin
from .options import AnalysisType, OptionList, parse_analysis_types, parse_options
from .pms import PmsDirectory, PmsProject
from .release import MeasurementStandards, ReferenceSet
from .taxonomy import PlatformMode, ProductPath, ProductTaxonomy

__all__ = [
    "AnalysisType", "ConditionMapping", "HeatExchangerType", "Mark", "HxCatalog", "HxEntry", "HxSpec", "MeasurementStandards",
    "OptionList", "PlatformMode", "PmsDirectory", "PmsProject", "ProductPath", "ProductTaxonomy",
    "ReferenceDataError", "ReferenceSet", "classify", "is_flat_fin", "parse_analysis_types",
    "parse_options",
]
