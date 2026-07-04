import math

from xhs_ceramics_analytics.analytics.numeric import is_finite_number, to_finite_float


def test_is_finite_number_accepts_real_finite_numbers():
    assert is_finite_number(1)
    assert is_finite_number(-2.5)
    assert is_finite_number(0)


def test_is_finite_number_rejects_none_bool_str_and_non_finite():
    assert not is_finite_number(None)
    assert not is_finite_number(True)  # bool is not a number here
    assert not is_finite_number("1")
    assert not is_finite_number(float("nan"))
    assert not is_finite_number(float("inf"))
    assert not is_finite_number(float("-inf"))


def test_to_finite_float_passes_through_finite_numbers():
    assert to_finite_float(3) == 3.0
    assert to_finite_float(-1.25) == -1.25


def test_to_finite_float_coerces_dirty_numeric_strings():
    assert to_finite_float("1,234") == 1234.0
    assert to_finite_float("¥1200") == 1200.0
    assert to_finite_float("  42 ") == 42.0
    # A trailing percent is stripped but NOT rescaled — the /100 convention is the
    # caller's (e.g. bounded_rate). "12%" therefore parses to 12.0.
    assert to_finite_float("12%") == 12.0


def test_to_finite_float_returns_default_on_uncoercible():
    assert to_finite_float(None) is None
    assert to_finite_float("—") is None
    assert to_finite_float("N/A") is None
    assert to_finite_float("") is None
    assert to_finite_float(True) is None
    assert to_finite_float(float("nan")) is None
    assert to_finite_float(float("inf")) is None
    assert to_finite_float("abc", 0.0) == 0.0


def test_to_finite_float_never_raises_on_arbitrary_objects():
    assert to_finite_float(object()) is None
    assert to_finite_float([1, 2], -1.0) == -1.0


def test_to_finite_float_result_is_always_finite_when_not_default():
    for value in ("1,000", "3.5", 7, "¥88"):
        result = to_finite_float(value)
        assert result is not None and math.isfinite(result)
