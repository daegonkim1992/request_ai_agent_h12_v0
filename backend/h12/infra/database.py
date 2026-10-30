"""SQLAlchemy 저장소 — 5단계 DB 경계."""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Iterator

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, selectinload, sessionmaker
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from h12.application import ConcurrentModification
from h12.domain.workflow import PendingKind, PendingRequest, Request, ResultRound, Revision, Role, User, WorkflowEvent


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    department: Mapped[str] = mapped_column(String(200), nullable=False)


class RequestRow(Base):
    __tablename__ = "requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requester_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    requester_department: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    analyst_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    held_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    request_no: Mapped[str | None] = mapped_column(String(30), nullable=True, unique=True)
    form: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    pending: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    current_revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    revisions: Mapped[list[RequestRevisionRow]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="RequestRevisionRow.revision_no"
    )
    events: Mapped[list[WorkflowEventRow]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="WorkflowEventRow.seq"
    )
    results: Mapped[list[ResultRow]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="ResultRow.round_no"
    )

    __mapper_args__ = {"version_id_col": version_id}


class RequestRevisionRow(Base):
    __tablename__ = "request_revisions"
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), primary_key=True)
    revision_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cause_event: Mapped[str] = mapped_column(String(50), nullable=False)

    request: Mapped[RequestRow] = relationship(back_populates="revisions")


class WorkflowEventRow(Base):
    __tablename__ = "workflow_events"
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    from_status: Mapped[str] = mapped_column(String(50), nullable=False)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    comment: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    request: Mapped[RequestRow] = relationship(back_populates="events")


class ResultRow(Base):
    __tablename__ = "request_results"
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), primary_key=True)
    round_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    registered_by: Mapped[str] = mapped_column(String(100), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    request: Mapped[RequestRow] = relationship(back_populates="results")


class NumberSequenceRow(Base):
    __tablename__ = "request_number_sequences"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    version_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version_id}


class Database:
    def __init__(self, url: str):
        self.engine = create_engine(url, future=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        legacy = self._prepare_legacy_snapshot_migration()
        Base.metadata.create_all(self.engine)
        if legacy is not None:
            self._restore_legacy_snapshot(*legacy)

    def _prepare_legacy_snapshot_migration(self) -> tuple[list[Any], list[Any]] | None:
        """기존 snapshot DB를 이관할 준비를 하고, 중단된 이관도 재개한다."""
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        backup = "requests_legacy_snapshot"
        sequence_backup = "request_number_sequences_legacy"
        if backup in tables:
            if "requests" in tables:
                with self.engine.connect() as connection:
                    if connection.execute(text("SELECT COUNT(*) FROM requests")).scalar_one():
                        raise RuntimeError("중단된 snapshot DB 이관의 대상 requests에 데이터가 있어 자동 복구할 수 없다")
            self._drop_indexes(inspector.get_indexes(backup))
            return self._read_legacy_snapshot(backup, sequence_backup if sequence_backup in tables else None)
        if "requests" not in tables or "snapshot" not in {column["name"] for column in inspector.get_columns("requests")}:
            return None

        legacy = self._read_legacy_snapshot("requests", "request_number_sequences" if "request_number_sequences" in tables else None)
        request_indexes = inspector.get_indexes("requests")
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE requests RENAME TO requests_legacy_snapshot"))
            self._drop_indexes(request_indexes, connection=connection)
            if "request_number_sequences" in tables:
                connection.execute(text(
                    "ALTER TABLE request_number_sequences RENAME TO request_number_sequences_legacy"
                ))
        return legacy

    def _read_legacy_snapshot(self, request_table: str, sequence_table: str | None) -> tuple[list[Any], list[Any]]:
        with self.engine.connect() as connection:
            snapshots = list(connection.execute(text(f"SELECT snapshot FROM {request_table}")).scalars())
            sequence_rows = [] if sequence_table is None else list(connection.execute(
                text(f"SELECT day, last_sequence FROM {sequence_table}")
            ).mappings())
        return snapshots, sequence_rows

    def _drop_indexes(self, indexes: list[dict[str, Any]], *, connection=None) -> None:
        quote = self.engine.dialect.identifier_preparer.quote
        if connection is None:
            with self.engine.begin() as owned_connection:
                self._drop_indexes(indexes, connection=owned_connection)
            return
        for index in indexes:
            name = index.get("name")
            if name:
                connection.execute(text(f"DROP INDEX {quote(name)}"))

    def _restore_legacy_snapshot(self, snapshots: list[Any], sequence_rows: list[Any]) -> None:
        with self.work() as work:
            for snapshot in snapshots:
                document = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
                work.save_request(_request_from_snapshot(document))
            for row in sequence_rows:
                day = row["day"]
                work.session.add(NumberSequenceRow(
                    day=date.fromisoformat(day) if isinstance(day, str) else day,
                    last_sequence=row["last_sequence"], version_id=1,
                ))
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE requests_legacy_snapshot"))
            connection.execute(text("DROP TABLE IF EXISTS request_number_sequences_legacy"))

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        try:
            with self.sessions.begin() as session:
                yield session
        except (IntegrityError, StaleDataError) as error:
            raise ConcurrentModification("다른 사용자가 먼저 저장했다. 최신 내용을 조회한 뒤 다시 시도해야 한다") from error

    @contextmanager
    def work(self) -> Iterator[SqlWork]:
        with self.transaction() as session:
            yield SqlWork(session)


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, user_id: str) -> User | None:
        row = self.session.get(UserRow, user_id)
        return User(row.id, Role(row.role), row.department) if row else None

    def save(self, user: User) -> None:
        row = self.session.get(UserRow, user.id)
        if row is None:
            self.session.add(UserRow(id=user.id, role=user.role.value, department=user.department))
        else:
            row.role, row.department = user.role.value, user.department


class RequestRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, request_id: str) -> Request | None:
        row = self.session.get(RequestRow, request_id)
        return _request_from_row(row) if row else None

    def list(self) -> list[Request]:
        rows = self.session.scalars(
            select(RequestRow)
            .options(
                selectinload(RequestRow.revisions),
                selectinload(RequestRow.events),
                selectinload(RequestRow.results),
            )
            .order_by(RequestRow.created_at.desc())
        ).all()
        return [_request_from_row(row) for row in rows]

    def save(self, request: Request) -> None:
        row = self.session.get(RequestRow, request.id)
        if row is None:
            if request.version not in (0, 1):
                raise ConcurrentModification("이미 변경된 의뢰를 새 의뢰로 저장할 수 없다")
            row = RequestRow(id=request.id, requester_id=request.requester_id,
                             requester_department=request.requester_department, status=request.status,
                             analyst_id=request.analyst_id, held_by=request.held_by, created_at=request.created_at,
                             request_no=_request_no(request.form), form=copy.deepcopy(request.form), pending=_pending_to_doc(request.pending),
                             current_revision_no=len(request.revisions), version_id=1)
            self.session.add(row)
        else:
            self.session.refresh(row)
            if row.version_id != request.version:
                raise ConcurrentModification("다른 사용자가 먼저 저장했다. 최신 내용을 조회한 뒤 다시 시도해야 한다")
            row.requester_id, row.requester_department = request.requester_id, request.requester_department
            row.status, row.analyst_id, row.held_by = request.status, request.analyst_id, request.held_by
            row.request_no = _request_no(request.form)
            row.form, row.pending = copy.deepcopy(request.form), _pending_to_doc(request.pending)
            row.current_revision_no = len(request.revisions)
        self._append_history(row, request)
        self.session.flush()
        request.version = row.version_id

    @staticmethod
    def _append_history(row: RequestRow, request: Request) -> None:
        revision_nos = {item.revision_no for item in row.revisions}
        for revision in request.revisions:
            if revision.revision_no not in revision_nos:
                row.revisions.append(RequestRevisionRow(
                    revision_no=revision.revision_no, snapshot=copy.deepcopy(revision.form),
                    created_by=revision.created_by, created_at=revision.created_at, cause_event=revision.cause_event,
                ))
        event_seqs = {item.seq for item in row.events}
        for event in request.events:
            if event.seq not in event_seqs:
                row.events.append(WorkflowEventRow(
                    seq=event.seq, event_type=event.event_type, action=event.action,
                    from_status=event.from_status, to_status=event.to_status, actor_id=event.actor_id, at=event.at,
                    reason_code=event.reason_code, comment=event.comment, payload=copy.deepcopy(event.payload),
                ))
        round_nos = {item.round_no for item in row.results}
        for result in request.results:
            if result.round_no not in round_nos:
                row.results.append(ResultRow(
                    round_no=result.round_no, summary=result.summary,
                    registered_by=result.registered_by, registered_at=result.registered_at,
                ))


class SqlNumberIssuer:
    """날짜별 번호를 같은 DB 트랜잭션에서 증가시킨다. 취소된 번호도 되돌리지 않는다."""
    def __init__(self, session: Session, number_format: str):
        self.session, self.number_format = session, number_format

    def issue(self, day: date) -> str:
        row = self.session.get(NumberSequenceRow, day)
        if row is None:
            row = NumberSequenceRow(day=day, last_sequence=1)
            self.session.add(row)
        else:
            row.last_sequence += 1
        return self.number_format.format(date=day, seq=row.last_sequence)


class SqlWork:
    """application.Work 포트의 SQLAlchemy 구현."""
    def __init__(self, session: Session):
        self.session = session
        self.users = UserRepository(session)
        self.request_store = RequestRepository(session)

    def user(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    def save_user(self, user: User) -> None:
        self.users.save(user)

    def request(self, request_id: str) -> Request | None:
        return self.request_store.get(request_id)

    def requests(self) -> list[Request]:
        return self.request_store.list()

    def save_request(self, request: Request) -> None:
        self.request_store.save(request)

    def issue_number(self, day: date) -> int:
        row = self.session.get(NumberSequenceRow, day)
        if row is None:
            row = NumberSequenceRow(day=day, last_sequence=1)
            self.session.add(row)
        else:
            row.last_sequence += 1
        return row.last_sequence


def _pending_to_doc(pending: PendingRequest | None) -> dict[str, Any] | None:
    if pending is None:
        return None
    return {
        "kind": pending.kind.value, "requested_by": pending.requested_by,
        "comment": pending.comment, "requested_at": pending.requested_at.isoformat(),
        "proposed_form": copy.deepcopy(pending.proposed_form),
    }


def _request_no(form: dict[str, Any]) -> str | None:
    value = (form.get("basic_info") or {}).get("request_no")
    return value if isinstance(value, str) and value else None


def _request_from_snapshot(doc: dict[str, Any]) -> Request:
    pending = doc.get("pending")
    return Request(
        id=doc["id"], requester_id=doc["requester_id"], requester_department=doc["requester_department"],
        status=doc["status"], created_at=datetime.fromisoformat(doc["created_at"]), form=copy.deepcopy(doc["form"]),
        analyst_id=doc.get("analyst_id"), held_by=doc.get("held_by"),
        pending=None if pending is None else PendingRequest(PendingKind(pending["kind"]), pending["requested_by"],
            pending["comment"], datetime.fromisoformat(pending["requested_at"]), copy.deepcopy(pending.get("proposed_form"))),
        revisions=[Revision(r["revision_no"], copy.deepcopy(r["form"]), r["created_by"],
                   datetime.fromisoformat(r["created_at"]), r["cause_event"]) for r in doc.get("revisions", [])],
        results=[ResultRound(r["round_no"], r["summary"], r["registered_by"], datetime.fromisoformat(r["registered_at"]))
                 for r in doc.get("results", [])],
        events=[WorkflowEvent(e["seq"], e["event_type"], e["action"], e["from_status"], e["to_status"],
                e["actor_id"], datetime.fromisoformat(e["at"]), e.get("reason_code"), e.get("comment"),
                copy.deepcopy(e.get("payload") or {})) for e in doc.get("events", [])],
    )


def _request_from_row(row: RequestRow) -> Request:
    pending = row.pending
    return Request(
        id=row.id, requester_id=row.requester_id, requester_department=row.requester_department,
        status=row.status, created_at=row.created_at, form=copy.deepcopy(row.form),
        analyst_id=row.analyst_id, held_by=row.held_by,
        pending=None if pending is None else PendingRequest(PendingKind(pending["kind"]), pending["requested_by"],
            pending["comment"], datetime.fromisoformat(pending["requested_at"]), copy.deepcopy(pending.get("proposed_form"))),
        revisions=[Revision(r.revision_no, copy.deepcopy(r.snapshot), r.created_by, r.created_at, r.cause_event)
                   for r in row.revisions],
        results=[ResultRound(r.round_no, r.summary, r.registered_by, r.registered_at) for r in row.results],
        events=[WorkflowEvent(e.seq, e.event_type, e.action, e.from_status, e.to_status,
                e.actor_id, e.at, e.reason_code, e.comment, copy.deepcopy(e.payload or {})) for e in row.events],
        version=row.version_id,
    )
