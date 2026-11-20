"""Pure, dependency-free pipeline DAG used by the custom orchestrator (D6).

The graph validates itself at construction time: duplicate steps, unknown
dependencies and cycles are rejected before any step runs.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from ecuador_lakehouse.domain.errors import LakehouseError


class DagError(LakehouseError):
    """The pipeline definition is invalid (unknown step, duplicate or cycle)."""

    exit_code: ClassVar[int] = 2


@dataclass(frozen=True, slots=True)
class Step:
    """One named pipeline step and the steps it depends on."""

    name: str
    deps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        deps = tuple(self.deps)
        object.__setattr__(self, "deps", deps)
        if not self.name or self.name != self.name.strip():
            raise ValueError(f"step name must be non-empty and trimmed: {self.name!r}")
        seen: set[str] = set()
        for dependency in deps:
            if not dependency or dependency != dependency.strip():
                raise ValueError(f"step dependency must be non-empty and trimmed: {dependency!r}")
            if dependency in seen:
                raise ValueError(f"step {self.name!r} has duplicate dependency {dependency!r}")
            seen.add(dependency)


class Dag:
    """An immutable, validated directed acyclic graph of pipeline steps."""

    def __init__(self, steps: Iterable[Step]) -> None:
        declared: dict[str, Step] = {}
        for declared_step in steps:
            if declared_step.name in declared:
                raise DagError(f"duplicate step: {declared_step.name!r}")
            declared[declared_step.name] = declared_step
        for declared_step in declared.values():
            for dependency in declared_step.deps:
                if dependency not in declared:
                    raise DagError(
                        f"step {declared_step.name!r} depends on unknown step {dependency!r}"
                    )
        self._steps: dict[str, Step] = declared
        self._order = self._compute_order()

    def __len__(self) -> int:
        return len(self._steps)

    def __contains__(self, name: object) -> bool:
        return name in self._steps

    @property
    def steps(self) -> tuple[Step, ...]:
        """The declared steps in declaration order."""
        return tuple(self._steps.values())

    def get(self, name: str) -> Step:
        """Return one step, raising :class:`DagError` when it does not exist."""
        try:
            return self._steps[name]
        except KeyError as exc:
            raise DagError(f"unknown step: {name!r}") from exc

    def topological_order(self) -> list[str]:
        """Every step name in deterministic topological order (ties alphabetical)."""
        return list(self._order)

    def select(self, names: Iterable[str], include_upstream: bool = True) -> list[str]:
        """Return the selected steps in topological order.

        With ``include_upstream`` (the default) every transitive dependency of
        the selection is included, which is what ``--select STEP`` means.
        """
        requested = list(names)
        for name in requested:
            if name not in self._steps:
                raise DagError(f"unknown step: {name!r}")
        selected = set(requested)
        if include_upstream:
            pending = list(requested)
            while pending:
                current = pending.pop()
                for dependency in self._steps[current].deps:
                    if dependency not in selected:
                        selected.add(dependency)
                        pending.append(dependency)
        return [name for name in self._order if name in selected]

    def _compute_order(self) -> tuple[str, ...]:
        indegree = {name: len(step.deps) for name, step in self._steps.items()}
        dependents: dict[str, list[str]] = {name: [] for name in self._steps}
        for name, step in self._steps.items():
            for dependency in step.deps:
                dependents[dependency].append(name)
        ready = [name for name, degree in indegree.items() if degree == 0]
        heapq.heapify(ready)
        order: list[str] = []
        while ready:
            name = heapq.heappop(ready)
            order.append(name)
            for dependent in sorted(dependents[name]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(ready, dependent)
        if len(order) != len(self._steps):
            remaining = sorted(name for name, degree in indegree.items() if degree > 0)
            raise DagError(f"cycle detected involving steps: {', '.join(remaining)}")
        return tuple(order)
