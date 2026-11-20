"""Tests for the pure pipeline DAG and its validation rules."""

from __future__ import annotations

import pytest

from ecuador_lakehouse.domain.dag import Dag, DagError, Step
from ecuador_lakehouse.domain.errors import LakehouseError


def step(name: str, *deps: str) -> Step:
    return Step(name=name, deps=deps)


def test_step_defaults_to_no_dependencies() -> None:
    assert Step(name="acquire").deps == ()
    assert Step(name="load_raw", deps=["acquire"]).deps == ("acquire",)


@pytest.mark.parametrize(("name", "match"), [("", "name"), (" ", "name"), (" a", "name")])
def test_step_rejects_invalid_names(name: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        Step(name=name)


def test_step_rejects_duplicate_dependencies() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        Step(name="b", deps=("a", "a"))


def test_dag_orders_steps_ties_alphabetically() -> None:
    dag = Dag([step("d"), step("b", "a"), step("c", "a"), step("a")])

    assert dag.topological_order() == ["a", "b", "c", "d"]
    assert len(dag) == 4
    assert "b" in dag
    assert "z" not in dag


def test_dag_rejects_duplicate_steps() -> None:
    with pytest.raises(DagError, match="duplicate"):
        Dag([step("a"), step("a")])


def test_dag_rejects_unknown_dependencies() -> None:
    with pytest.raises(DagError, match="unknown"):
        Dag([step("b", "missing")])


def test_dag_rejects_self_dependency() -> None:
    with pytest.raises(DagError, match="cycle"):
        Dag([step("a", "a")])


def test_dag_rejects_cycles() -> None:
    with pytest.raises(DagError, match="cycle"):
        Dag([step("a", "c"), step("b", "a"), step("c", "b")])


def test_dag_error_is_a_lakehouse_error_with_a_usage_exit_code() -> None:
    error = DagError("cycle detected")

    assert isinstance(error, LakehouseError)
    assert error.exit_code == 2


def test_dag_get_returns_the_step() -> None:
    dag = Dag([step("a")])

    assert dag.get("a") == Step("a")
    with pytest.raises(DagError, match="unknown"):
        dag.get("missing")


def test_select_includes_upstream_by_default() -> None:
    dag = Dag([step("a"), step("b", "a"), step("c", "b"), step("d")])

    assert dag.select(["c"]) == ["a", "b", "c"]
    assert dag.select(["b", "d"]) == ["a", "b", "d"]


def test_select_can_exclude_upstream() -> None:
    dag = Dag([step("a"), step("b", "a"), step("c", "b"), step("d")])

    assert dag.select(["c", "b"], include_upstream=False) == ["b", "c"]
    assert dag.select([], include_upstream=True) == []


def test_select_rejects_unknown_names() -> None:
    dag = Dag([step("a")])

    with pytest.raises(DagError, match="unknown"):
        dag.select(["missing"])


def test_dag_steps_property_exposes_the_declared_steps() -> None:
    dag = Dag([step("a"), step("b", "a")])

    assert {declared.name for declared in dag.steps} == {"a", "b"}
