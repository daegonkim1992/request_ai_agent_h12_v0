"""application 유스케이스의 5단계 회귀 검증."""

from __future__ import annotations

import copy
import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect, text

from h12.application import ConcurrentModification, RequestService
from h12.domain.form import InMemoryNumberIssuer, TargetSelection
from h12.domain.workflow import Request, ResultRound, Revision, Role, SubmissionBlocked, User, WorkflowEvent
from h12.infra import Database
from h12.reference import default_store
from h12.rulebook import load_form_rules

from tests.domain.form.conftest import NOW, make_form


def test_editing_non_case_content_keeps_case_confirmation():
    rules = load_form_rules()
    references = default_store()
    database = Database("sqlite://")
    database.create_all()
    service = RequestService(database, references, now=lambda: NOW)
    requester = User("requester", Role.REQUESTER, "CAE")
    service.add_user(requester)
    request = service.create(requester)

    form = make_form(rules, references.load(), InMemoryNumberIssuer(rules.target.request_no_format))
    with database.work() as work:
        stored = work.request(request.id)
        assert stored is not None
        stored.form = form
        work.save_request(stored)

    edited = copy.deepcopy(form)
    edited["analysis_overview"]["request_description"] = rules.values.cell("수정한 설명")
    changed = service.edit_form(requester, request.id, edited)

    assert changed.form["case_confirmation"] == form["case_confirmation"]


def test_measurement_edit_keeps_case_confirmation_but_geometry_edit_adds_default_case():
    rules = load_form_rules()
    references = default_store()
    database = Database("sqlite://")
    database.create_all()
    service = RequestService(database, references, now=lambda: NOW)
    requester = User("requester", Role.REQUESTER, "CAE")
    service.add_user(requester)
    request = service.create(requester)

    from h12.domain.form import TargetSelection
    path = references.load().taxonomy.find("SAC", "Multi V", "AHU", "10RT")
    service.confirm_target(requester, request.id, TargetSelection(path.id, "PDB"))
    current = service.get(requester, request.id)
    draft = copy.deepcopy(current.form)
    draft["geometry"] = {"base_product": {"id": "base", "drawing_no": rules.values.cell("MEA-1")},
                         "comparison_products": []}
    changed = service.edit_form(requester, request.id, draft)
    assert [(case["geometry_id"], case["condition_package_ids"]) for case in changed.form["cases"]] == [
        ("base", {"operating": None, "space_environment": None, "supply_air": None,
                  "heat_exchanger": None, "installation": None}),
    ]

    complete = make_form(rules, references.load(), InMemoryNumberIssuer(rules.target.request_no_format), "PDB")
    with database.work() as work:
        stored = work.request(request.id)
        stored.form = complete
        work.save_request(stored)
    edited = copy.deepcopy(complete)
    edited["conditions"]["measurement"]["temperature_criterion"]["value"] = "새 기준"
    assert "case_confirmation" in service.edit_form(requester, request.id, edited).form


def test_request_change_can_reconfirm_cases_with_the_explicit_input():
    rules = load_form_rules()
    references = default_store()
    database = Database("sqlite://")
    database.create_all()
    service = RequestService(database, references, now=lambda: NOW)
    requester = User("requester", Role.REQUESTER, "CAE")
    manager = User("manager", Role.MANAGER, "CAE")
    analyst = User("analyst", Role.ANALYST, "CAE")
    for user in (requester, manager, analyst):
        service.add_user(user)
    request = service.create(requester)
    path = references.load().taxonomy.find("SAC", "Multi V", "AHU", "10RT")
    assert path is not None
    service.confirm_target(requester, request.id, TargetSelection(path.id, "AIRFLOW_PATTERN"))
    service.edit_form(requester, request.id, make_form(
        rules, references.load(), InMemoryNumberIssuer(rules.target.request_no_format),
    ), confirm_case=True)
    service.action(requester, request.id, "submit", {})
    service.action(manager, request.id, "accept_and_assign", {"analyst_id": analyst.id})
    proposed = copy.deepcopy(service.get(requester, request.id).form)
    proposed["conditions"]["operating"]["packages"][0]["rpm"] = rules.values.cell(900)

    with pytest.raises(SubmissionBlocked):
        service.action(requester, request.id, "request_change", {"form": proposed, "comment": "회전수 변경"})

    changed = service.action(requester, request.id, "request_change", {
        "form": proposed, "comment": "회전수 변경", "confirm_case": True,
    })

    assert changed.pending is not None
    assert changed.pending.proposed_form["case_confirmation"]


def test_storage_rejects_stale_concurrent_update(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'h12.sqlite3').as_posix()}")
    database.create_all()
    with database.work() as work:
        work.save_request(Request(
            id="request-1", requester_id="requester", requester_department="CAE",
            status="DRAFT", created_at=datetime(2026, 11, 2, 9, 0),
        ))

    with pytest.raises(ConcurrentModification):
        with database.work() as first:
            stale = first.request("request-1")
            assert stale is not None
            with database.work() as second:
                current = second.request("request-1")
                assert current is not None
                current.status = "UNDER_REVIEW"
                second.save_request(current)
            stale.status = "REVISION_REQUESTED"
            first.save_request(stale)


def test_storage_reopens_normalized_history(tmp_path):
    url = f"sqlite:///{(tmp_path / 'h12.sqlite3').as_posix()}"
    created_at = datetime(2026, 11, 2, 9, 0)
    request = Request(
        id="request-1", requester_id="requester", requester_department="CAE", status="IN_PROGRESS",
        created_at=created_at, form={"basic_info": {"request_no": "CFD-20261102-001"}},
        revisions=[Revision(1, {"form": "submitted"}, "requester", created_at, "SUBMITTED")],
        results=[ResultRound(1, "결과", "analyst", created_at)],
        events=[WorkflowEvent(1, "SUBMITTED", "submit", "DRAFT", "UNDER_REVIEW", "requester", created_at)],
    )
    first = Database(url)
    first.create_all()
    with first.work() as work:
        work.save_request(request)

    reopened = Database(url)
    with reopened.work() as work:
        restored = work.request("request-1")

    assert restored is not None
    assert restored.form == request.form
    assert [item.revision_no for item in restored.revisions] == [1]
    assert [item.seq for item in restored.events] == [1]
    assert [item.round_no for item in restored.results] == [1]


def test_number_sequence_rejects_concurrent_first_issue_and_allows_retry(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'h12.sqlite3').as_posix()}")
    database.create_all()
    day = datetime(2026, 11, 2).date()

    with pytest.raises(ConcurrentModification):
        with database.work() as first:
            assert first.issue_number(day) == 1
            with database.work() as second:
                assert second.issue_number(day) == 1

    with database.work() as retry:
        assert retry.issue_number(day) == 2


def test_number_sequence_rejects_concurrent_increment(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'h12.sqlite3').as_posix()}")
    database.create_all()
    day = datetime(2026, 11, 2).date()
    with database.work() as initial:
        assert initial.issue_number(day) == 1

    with pytest.raises(ConcurrentModification):
        with database.work() as first:
            assert first.issue_number(day) == 2
            with database.work() as second:
                assert second.issue_number(day) == 2

    with database.work() as retry:
        assert retry.issue_number(day) == 3


def test_request_number_has_a_database_unique_constraint():
    database = Database("sqlite://")
    database.create_all()
    created_at = datetime(2026, 11, 2, 9, 0)
    with database.work() as work:
        work.save_request(Request(
            id="request-1", requester_id="requester", requester_department="CAE",
            status="DRAFT", created_at=created_at, form={"basic_info": {"request_no": "CFD-20261102-001"}},
        ))

    with pytest.raises(ConcurrentModification):
        with database.work() as work:
            work.save_request(Request(
                id="request-2", requester_id="requester", requester_department="CAE",
                status="DRAFT", created_at=created_at, form={"basic_info": {"request_no": "CFD-20261102-001"}},
            ))


def test_legacy_snapshot_database_is_migrated(tmp_path):
    url = f"sqlite:///{(tmp_path / 'h12.sqlite3').as_posix()}"
    created_at = datetime(2026, 11, 2, 9, 0)
    snapshot = {
        "id": "request-1", "requester_id": "requester", "requester_department": "CAE",
        "status": "DRAFT", "created_at": created_at.isoformat(), "form": {}, "analyst_id": None,
        "held_by": None, "pending": None, "revisions": [], "results": [], "events": [],
    }
    legacy = create_engine(url)
    with legacy.begin() as connection:
        connection.execute(text("CREATE TABLE requests (id VARCHAR(36) PRIMARY KEY, snapshot JSON NOT NULL)"))
        connection.execute(text(
            "CREATE TABLE request_number_sequences (day DATE PRIMARY KEY, last_sequence INTEGER NOT NULL)"
        ))
        connection.execute(text("INSERT INTO requests (id, snapshot) VALUES (:id, :snapshot)"), {
            "id": "request-1", "snapshot": json.dumps(snapshot),
        })
        connection.execute(text(
            "INSERT INTO request_number_sequences (day, last_sequence) VALUES (:day, :sequence)"
        ), {"day": "2026-11-02", "sequence": 4})
    legacy.dispose()

    database = Database(url)
    database.create_all()
    with database.work() as work:
        assert work.request("request-1") is not None
        assert work.issue_number(datetime(2026, 11, 2).date()) == 5

    columns = {column["name"] for column in inspect(database.engine).get_columns("requests")}
    assert "snapshot" not in columns
    assert {"form", "request_no", "version_id"} <= columns
    database.engine.dispose()


def test_todo_status_counts_are_calculated_from_the_todo_list():
    database = Database("sqlite://")
    database.create_all()
    service = RequestService(database, default_store(), now=lambda: NOW)
    manager = User("manager", Role.MANAGER, "CAE")
    service.add_user(manager)
    with database.work() as work:
        work.save_request(Request(
            id="request-1", requester_id="requester", requester_department="CAE",
            status="IN_PROGRESS", created_at=NOW,
        ))

    items, counts = service.list_with_status_counts(manager, todo_only=True)

    assert items == []
    assert counts == {}
