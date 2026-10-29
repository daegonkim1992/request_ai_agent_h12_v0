"""rules/workflow.yaml, rules/reason_codes.yaml 을 읽어 검증된 규칙 객체로 만든다.

파일 입출력은 하지 않는다. 읽은 dict 를 받아 해석만 한다 (h12.rulebook 이 파일을 읽는다).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import RulesError
from .model import PendingKind, Role

ACTORS = frozenset({"requester", "manager", "assigned_analyst", "holder"})
INPUTS = frozenset({"reason_code", "comment", "analyst", "form", "result_summary"})
CHECKS = frozenset({"submission"})
EFFECTS = frozenset({
    "create_revision", "assign_analyst", "record_holder", "clear_holder",
    "open_change", "apply_change", "open_cancel", "close_pending", "add_result",
})
# None 은 대기 요청이 없어야 함, PendingKind 는 그 요청이 대기 중이어야 함
PENDING_CONDITIONS: dict[str, PendingKind | None] = {
    "none": None,
    "change": PendingKind.CHANGE,
    "cancel": PendingKind.CANCEL,
}


@dataclass(frozen=True)
class ActionRule:
    key: str
    label: str
    event: str
    actors: tuple[str, ...]
    # 현재 상태 → 결과 상태. 결과가 None 이면 상태 유지
    transitions: Mapping[str, str | None]
    # 허용하는 대기 요청 (None 원소는 대기 요청 없음). 필드가 None 이면 따지지 않는다
    pending: frozenset[PendingKind | None] | None = None
    requires: frozenset[str] = frozenset()
    reason_codes: str | None = None
    checks: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class TodoRule:
    relation: str | None = None
    statuses: frozenset[str] | None = None
    pending: PendingKind | None = None


@dataclass(frozen=True)
class WorkflowRules:
    statuses: Mapping[str, str]  # 이름 → 라벨
    terminal_statuses: frozenset[str]
    initial_status: str
    editable_statuses: frozenset[str]
    # 대기 중이면 그 요청을 처리하는 기능 외에는 모두 막는 대기 요청
    exclusive_pending: frozenset[PendingKind]
    actions: Mapping[str, ActionRule]
    todo: Mapping[Role, tuple[TodoRule, ...]]
    reason_codes: Mapping[str, Mapping[str, str]]

    @classmethod
    def from_dicts(cls, workflow: Mapping[str, Any], reason_codes: Mapping[str, Any]) -> WorkflowRules:
        return _Parser(workflow, reason_codes).parse()


class _Parser:
    def __init__(self, workflow: Mapping[str, Any], reason_codes: Mapping[str, Any]):
        self.raw = workflow
        self.reason_codes = {name: dict(codes) for name, codes in (reason_codes or {}).items()}

    def parse(self) -> WorkflowRules:
        raw_statuses = self.raw.get("statuses") or {}
        if not raw_statuses:
            raise RulesError("statuses 가 비어 있다")
        self.statuses = {name: (spec or {}).get("label", name) for name, spec in raw_statuses.items()}
        terminal = frozenset(n for n, spec in raw_statuses.items() if (spec or {}).get("terminal"))

        actions: dict[str, ActionRule] = {}
        events: set[str] = set()
        for key, spec in (self.raw.get("actions") or {}).items():
            action = self._action(key, spec or {}, terminal)
            if action.event in events:
                raise RulesError(f"{key}: event {action.event} 가 중복된다")
            events.add(action.event)
            actions[key] = action

        return WorkflowRules(
            statuses=self.statuses,
            terminal_statuses=terminal,
            initial_status=self._status(self.raw.get("initial_status"), "initial_status"),
            editable_statuses=self._status_set(self.raw.get("editable_statuses"), "editable_statuses"),
            exclusive_pending=self._exclusive_pending(self.raw.get("exclusive_pending")),
            actions=actions,
            todo=self._todo(self.raw.get("todo") or {}),
            reason_codes=self.reason_codes,
        )

    def _action(self, key: str, spec: Mapping[str, Any], terminal: frozenset[str]) -> ActionRule:
        where = f"actions.{key}"
        transitions = {}
        for source, target in (spec.get("transitions") or {}).items():
            self._status(source, f"{where}.transitions")
            if source in terminal:
                raise RulesError(f"{where}: 종료 상태 {source} 에서 시작할 수 없다 (3.4-8)")
            transitions[source] = None if target is None else self._status(target, f"{where}.transitions")
        if not transitions:
            raise RulesError(f"{where}: transitions 가 비어 있다")

        requires = frozenset(self._names(spec.get("requires"), INPUTS, f"{where}.requires"))
        reason_set = spec.get("reason_codes")
        if ("reason_code" in requires) != (reason_set is not None):
            raise RulesError(f"{where}: reason_code 와 reason_codes 는 함께 써야 한다")
        if reason_set is not None and reason_set not in self.reason_codes:
            raise RulesError(f"{where}: 사유 코드 집합 {reason_set} 이 없다")

        pending = None
        if "pending" in spec:
            raw_pending = spec["pending"]
            names = raw_pending if isinstance(raw_pending, list) else [raw_pending]
            unknown = [n for n in names if n not in PENDING_CONDITIONS]
            if unknown or not names:
                raise RulesError(f"{where}.pending: {raw_pending!r} 은 알 수 없다")
            pending = frozenset(PENDING_CONDITIONS[n] for n in names)

        actors = tuple(self._names(spec.get("actors"), ACTORS, f"{where}.actors"))
        if not actors:
            raise RulesError(f"{where}: actors 가 비어 있다")
        if not spec.get("event"):
            raise RulesError(f"{where}: event 가 없다")

        return ActionRule(
            key=key,
            label=spec.get("label", key),
            event=spec["event"],
            actors=actors,
            transitions=transitions,
            pending=pending,
            requires=requires,
            reason_codes=reason_set,
            checks=tuple(self._names(spec.get("checks"), CHECKS, f"{where}.checks")),
            effects=tuple(self._names(spec.get("effects"), EFFECTS, f"{where}.effects")),
        )

    def _todo(self, raw: Mapping[str, Any]) -> dict[Role, tuple[TodoRule, ...]]:
        todo: dict[Role, tuple[TodoRule, ...]] = {}
        for role_name, items in raw.items():
            try:
                role = Role(role_name)
            except ValueError:
                raise RulesError(f"todo: 역할 {role_name} 은 알 수 없다") from None
            parsed = []
            for item in items or []:
                relation = item.get("relation")
                if relation is not None and relation not in ACTORS:
                    raise RulesError(f"todo.{role_name}: relation {relation} 은 알 수 없다")
                pending = item.get("pending")
                if pending is not None and PENDING_CONDITIONS.get(pending) is None:
                    raise RulesError(f"todo.{role_name}: pending {pending} 은 change 나 cancel 이어야 한다")
                statuses = item.get("statuses")
                parsed.append(TodoRule(
                    relation=relation,
                    statuses=None if statuses is None else self._status_set(statuses, f"todo.{role_name}"),
                    pending=None if pending is None else PENDING_CONDITIONS[pending],
                ))
            todo[role] = tuple(parsed)
        return todo

    @staticmethod
    def _exclusive_pending(names: Any) -> frozenset[PendingKind]:
        kinds = set()
        for name in names or []:
            if PENDING_CONDITIONS.get(name) is None:
                raise RulesError(f"exclusive_pending: {name!r} 은 change 나 cancel 이어야 한다")
            kinds.add(PENDING_CONDITIONS[name])
        return frozenset(kinds)

    def _status(self, name: Any, where: str) -> str:
        if name not in self.statuses:
            raise RulesError(f"{where}: 상태 {name!r} 은 statuses 에 없다")
        return name

    def _status_set(self, names: Any, where: str) -> frozenset[str]:
        return frozenset(self._status(n, where) for n in names or [])

    @staticmethod
    def _names(names: Any, known: frozenset[str], where: str) -> list[str]:
        names = list(names or [])
        unknown = [n for n in names if n not in known]
        if unknown:
            raise RulesError(f"{where}: {unknown} 은 엔진이 모르는 이름이다")
        return names
