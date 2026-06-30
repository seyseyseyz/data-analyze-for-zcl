from datetime import datetime

from xhs_ceramics_analytics.contracts.normalize import normalize_order_rows
from xhs_ceramics_analytics.contracts.schemas import Note, OrderLine


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
