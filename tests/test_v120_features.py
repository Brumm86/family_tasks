"""v1.2: Laptopzeit-Schwellen (Optionen, feste Minuten, Aufsteigend-Prüfung)."""

from custom_components.family_tasks.const import (
    DEFAULT_LAPTOP_THRESHOLD_POINTS,
    LAPTOP_THRESHOLD_KEYS,
    LAPTOP_THRESHOLD_MINUTES,
    laptop_thresholds_ascending,
)


def test_laptop_minutes_add_up_to_daily_maximum() -> None:
    assert LAPTOP_THRESHOLD_MINUTES == (10, 10, 20, 20)
    assert sum(LAPTOP_THRESHOLD_MINUTES) == 60
    assert len(LAPTOP_THRESHOLD_KEYS) == len(LAPTOP_THRESHOLD_MINUTES) == 4


def test_laptop_thresholds_default_off() -> None:
    assert DEFAULT_LAPTOP_THRESHOLD_POINTS == 0
    assert laptop_thresholds_ascending((0, 0, 0, 0))


def test_laptop_thresholds_ascending() -> None:
    assert laptop_thresholds_ascending((10, 20, 30, 40))
    assert laptop_thresholds_ascending((0, 20, 0, 40))
    assert laptop_thresholds_ascending((10, 0, 0, 0))


def test_laptop_thresholds_not_ascending() -> None:
    assert not laptop_thresholds_ascending((20, 10, 30, 40))
    assert not laptop_thresholds_ascending((10, 10, 30, 40))
    assert not laptop_thresholds_ascending((10, 30, 0, 20))
