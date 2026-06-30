from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pandas as pd

from xhs_ceramics_analytics.contracts.schemas import OrderLine


def is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def parse_datetime(value: object) -> datetime | None:
    if is_missing(value):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).strip().replace("/", "-"))


def parse_required_text(value: object, field_name: str) -> str:
    if is_missing(value):
        raise ValueError(f"{field_name} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def parse_quantity(value: object) -> int:
    if is_missing(value):
        raise ValueError("quantity is required")
    if isinstance(value, bool):
        raise ValueError("quantity must be an integer")

    try:
        quantity = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError("quantity must be an integer") from exc

    if not quantity.is_finite() or quantity != quantity.to_integral_value():
        raise ValueError("quantity must be an integer")
    return int(quantity)


def parse_optional_float(value: object) -> float | None:
    if is_missing(value):
        return None
    number = float(value)
    if is_missing(number):
        return None
    return number


def parse_optional_text(value: object) -> str | None:
    if is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def normalize_order_rows(rows: list[Mapping[str, object]]) -> list[OrderLine]:
    normalized: list[OrderLine] = []
    for row in rows:
        normalized.append(
            OrderLine(
                order_id=parse_required_text(row.get("order_id"), "order_id"),
                paid_time=parse_datetime(row.get("paid_time")),
                sku_id=parse_required_text(row.get("sku_id"), "sku_id"),
                quantity=parse_quantity(row.get("quantity", 1)),
                paid_amount=parse_optional_float(row.get("paid_amount")),
                refund_status_optional=parse_optional_text(row.get("refund_status_optional")),
            )
        )
    return normalized
