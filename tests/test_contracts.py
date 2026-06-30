from datetime import datetime

import pytest

from xhs_ceramics_analytics.contracts.normalize import normalize_order_rows
from xhs_ceramics_analytics.contracts.schemas import Note, NoteSkuLink, OrderLine, Product, Sku


def _order_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "order_id": "o1",
        "paid_time": "2026-06-02 12:00:00",
        "sku_id": "s1",
        "quantity": "2",
        "paid_amount": "198.00",
        "refund_status_optional": "none",
    }
    row.update(overrides)
    return row


def _assert_normalize_error_context(overrides: dict[str, object], *snippets: str) -> None:
    with pytest.raises(ValueError) as exc_info:
        normalize_order_rows([_order_row(**overrides)])

    message = str(exc_info.value)
    for snippet in snippets:
        assert snippet in message


def test_note_accepts_core_fields():
    note = Note(
        note_id="n1",
        publish_time=datetime(2026, 6, 1, 9, 0),
        title="一只适合夏天的杯子",
        body="低饱和釉色，适合咖啡和茶。",
        note_type="image",
        cover_image_path="covers/n1.jpg",
        reads=1200,
        likes=80,
        collects=35,
        comments=6,
    )
    assert note.note_id == "n1"
    assert note.impressions is None


def test_order_line_rejects_negative_quantity():
    try:
        OrderLine(order_id="o1", paid_time=datetime(2026, 6, 2), sku_id="s1", quantity=-1)
    except ValueError as exc:
        assert "quantity" in str(exc)
    else:
        raise AssertionError("negative quantity should fail")


def test_normalize_order_rows_preserves_sku_lines():
    rows = [
        {"order_id": "o1", "paid_time": "2026-06-02 12:00:00", "sku_id": "s1", "quantity": "2", "paid_amount": "198.00"},
        {"order_id": "o1", "paid_time": "2026-06-02 12:00:00", "sku_id": "s2", "quantity": "1", "paid_amount": "88.00"},
    ]
    normalized = normalize_order_rows(rows)
    assert [line.sku_id for line in normalized] == ["s1", "s2"]
    assert sum(line.quantity for line in normalized) == 3


@pytest.mark.parametrize("order_id", [None, "   "])
def test_normalize_order_rows_rejects_missing_order_id(order_id: object):
    _assert_normalize_error_context({"order_id": order_id}, "order_id", "row index 0")


@pytest.mark.parametrize("sku_id", [None, "   "])
def test_normalize_order_rows_rejects_missing_sku_id(sku_id: object):
    _assert_normalize_error_context({"sku_id": sku_id}, "sku_id", "row index 0")


def test_normalize_order_rows_rejects_fractional_quantity():
    with pytest.raises(ValueError, match="quantity"):
        normalize_order_rows([_order_row(quantity="2.5")])


def test_normalize_order_rows_accepts_decimal_integer_quantity():
    normalized = normalize_order_rows([_order_row(quantity="2.0")])

    assert normalized[0].quantity == 2


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("price", -1.0),
        ("inventory_optional", -1),
        ("cost_optional", -1.0),
    ],
)
def test_sku_rejects_negative_numeric_fields(field_name: str, value: object):
    with pytest.raises(ValueError, match=field_name):
        Sku(sku_id="s1", **{field_name: value})


def test_sku_rejects_infinite_price():
    with pytest.raises(ValueError, match="price"):
        Sku(sku_id="s1", price=float("inf"))


def test_order_line_rejects_negative_paid_amount():
    with pytest.raises(ValueError, match="paid_amount"):
        OrderLine(order_id="o1", paid_time=datetime(2026, 6, 2), sku_id="s1", paid_amount=-1)


def test_order_line_rejects_infinite_paid_amount():
    with pytest.raises(ValueError, match="paid_amount"):
        OrderLine(
            order_id="o1",
            paid_time=datetime(2026, 6, 2),
            sku_id="s1",
            paid_amount=float("inf"),
        )


def test_normalize_order_rows_rejects_infinite_paid_amount_with_context():
    with pytest.raises(ValueError, match=r"paid_amount.*row index 0"):
        normalize_order_rows([_order_row(paid_amount="inf")])


def test_normalize_order_rows_rejects_non_positive_quantity_with_context():
    _assert_normalize_error_context({"quantity": "0"}, "quantity", "row index 0")


def test_normalize_order_rows_rejects_negative_paid_amount_with_context():
    _assert_normalize_error_context({"paid_amount": "-1"}, "paid_amount", "row index 0")


def test_normalize_order_rows_treats_optional_missing_values_as_none():
    normalized = normalize_order_rows(
        [
            _order_row(
                paid_time=float("nan"),
                paid_amount=float("nan"),
                refund_status_optional="   ",
            )
        ]
    )

    assert normalized[0].paid_time is None
    assert normalized[0].paid_amount is None
    assert normalized[0].refund_status_optional is None


@pytest.mark.parametrize(
    ("model_cls", "kwargs", "field_name"),
    [
        (Note, {"note_id": "   "}, "note_id"),
        (Sku, {"sku_id": ""}, "sku_id"),
        (Product, {"product_id": "   "}, "product_id"),
        (OrderLine, {"order_id": "", "sku_id": "s1"}, "order_id"),
        (
            NoteSkuLink,
            {"note_id": "   ", "sku_id": "s1", "link_type": "explicit", "confidence": 1.0},
            "note_id",
        ),
        (
            NoteSkuLink,
            {"note_id": "n1", "sku_id": "", "link_type": "explicit", "confidence": 1.0},
            "sku_id",
        ),
    ],
)
def test_required_ids_reject_blank_values(
    model_cls: type, kwargs: dict[str, object], field_name: str
):
    with pytest.raises(ValueError, match=field_name):
        model_cls(**kwargs)


def test_required_ids_are_trimmed():
    link = NoteSkuLink(
        note_id=" n1 ",
        sku_id=" s1 ",
        link_type="explicit",
        confidence=1.0,
    )

    assert link.note_id == "n1"
    assert link.sku_id == "s1"
