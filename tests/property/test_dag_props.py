"""Property-based tests for topological ordering and cycle detection."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ecuador_lakehouse.domain.dag import Dag, DagError, Step


def _random_acyclic_steps(data: st.DataObject, min_size: int = 1) -> list[Step]:
    size = data.draw(st.integers(min_value=min_size, max_value=8), label="size")
    permutation = data.draw(st.permutations(range(size)), label="permutation")
    steps: list[Step] = []
    for position, node in enumerate(permutation):
        available = [f"s{candidate}" for candidate in permutation[:position]]
        deps = (
            data.draw(st.lists(st.sampled_from(available), unique=True), label="deps")
            if available
            else []
        )
        steps.append(Step(name=f"s{node}", deps=tuple(sorted(deps))))
    return steps


@settings(max_examples=100, deadline=None)
@given(data=st.data())
def test_topological_order_respects_every_edge(data: st.DataObject) -> None:
    steps = _random_acyclic_steps(data)
    order = Dag(steps).topological_order()

    positions = {name: index for index, name in enumerate(order)}
    assert set(order) == {step.name for step in steps}
    for declared in steps:
        for dependency in declared.deps:
            assert positions[dependency] < positions[declared.name]


@settings(max_examples=100, deadline=None)
@given(data=st.data())
def test_any_two_node_cycle_is_always_detected(data: st.DataObject) -> None:
    steps = _random_acyclic_steps(data, min_size=2)
    first, second = data.draw(
        st.lists(
            st.sampled_from([step.name for step in steps]),
            min_size=2,
            max_size=2,
            unique=True,
        ),
        label="cycle pair",
    )

    mutated = [
        Step(
            name=declared.name,
            deps=(second,)
            if declared.name == first
            else (first,)
            if declared.name == second
            else declared.deps,
        )
        for declared in steps
    ]

    with pytest.raises(DagError, match="cycle"):
        Dag(mutated)
