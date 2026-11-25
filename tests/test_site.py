import pytest

from septa_detours.export.contract import Mode
from septa_detours.export.site import MODE_ORDER, route_mode, route_sort_key


@pytest.mark.parametrize(
    ("route_type", "mode"),
    [(0, "trolley"), (1, "metro"), (2, "rail"), (3, "bus"), (11, "trackless")],
)
def test_route_mode(route_type: int, mode: Mode) -> None:
    assert route_mode(route_type) == mode


@pytest.mark.parametrize("route_type", [4, 7, 12, -1])
def test_route_mode_rejects_unknown_types(route_type: int) -> None:
    with pytest.raises(ValueError, match=f"unknown route_type {route_type}"):
        route_mode(route_type)


def test_mode_order() -> None:
    assert MODE_ORDER == ("metro", "trolley", "trackless", "bus", "rail")


def sort_names(mode: Mode, names: list[str]) -> list[str]:
    return sorted(names, key=lambda name: route_sort_key(mode, name))


def test_modes_sort_in_mode_order() -> None:
    routes: list[tuple[Mode, str]] = [
        ("rail", "AIR"),
        ("bus", "1"),
        ("trackless", "59"),
        ("metro", "L1"),
        ("trolley", "T1"),
    ]
    result = sorted(routes, key=lambda route: route_sort_key(*route))
    assert [mode for mode, _ in result] == list(MODE_ORDER)


def test_mode_beats_name() -> None:
    routes: list[tuple[Mode, str]] = [("bus", "1"), ("metro", "B1"), ("metro", "9")]
    result = sorted(routes, key=lambda route: route_sort_key(*route))
    assert result == [("metro", "9"), ("metro", "B1"), ("bus", "1")]


def test_numbers_sort_by_value() -> None:
    assert sort_names("bus", ["10", "9", "124", "2"]) == ["2", "9", "10", "124"]


def test_real_bus_names_sort_numbers_first_then_alphabetically() -> None:
    # The real non-numeric bus short names (GTFS, 2026-11-25), shuffled.
    names = [
        "WTR Bus", "K", "124", "LUCYGR", "D2 Bus", "MANN", "1", "B1 OWL",
        "NOR Bus", "FOX Bus", "L1 OWL", "T Bus", "BLVDDIR", "M1 Bus", "D1 Bus",
        "LUCYGO", "21",
    ]  # fmt: skip
    assert sort_names("bus", names) == [
        "1", "21", "124", "B1 OWL", "BLVDDIR", "D1 Bus", "D2 Bus", "FOX Bus",
        "K", "L1 OWL", "LUCYGO", "LUCYGR", "M1 Bus", "MANN", "NOR Bus",
        "T Bus", "WTR Bus",
    ]  # fmt: skip


def test_names_ignore_case() -> None:
    assert sort_names("bus", ["b", "C", "A"]) == ["A", "b", "C"]


@pytest.mark.parametrize("names", [["K", "k"], ["k", "K"]])
def test_names_equal_ignoring_case_have_a_fixed_order(names: list[str]) -> None:
    assert sort_names("bus", names) == ["K", "k"]


@pytest.mark.parametrize("name", ["10B", "1 Bus", "\u00b2", "\u0663", "-1", ""])
def test_names_that_are_not_plain_numbers_sort_as_text(name: str) -> None:
    assert sort_names("bus", [name, "999"]) == ["999", name]
