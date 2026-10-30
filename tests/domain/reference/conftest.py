"""기준 데이터 테스트 공통 준비. 저장소의 현재 릴리스를 읽는다."""

from __future__ import annotations

import pytest

from h12.reference import default_store


@pytest.fixture(scope="session")
def ref():
    return default_store().load()


@pytest.fixture
def taxonomy(ref):
    return ref.taxonomy


@pytest.fixture
def catalog(ref):
    return ref.hx_catalog


@pytest.fixture
def pms(ref):
    return ref.pms
