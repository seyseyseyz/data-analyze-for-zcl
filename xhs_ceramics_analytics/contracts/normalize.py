from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
import math

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


def parse_error(
    message: str, field_name: str | None = None, row_index: int | None = None
) -> ValueError:
    if field_name is None and row_index is None:
        return ValueError(message)

    context = field_name or ""
    if row_index is not None:
        row_context = f"row index {row_index}"
        context = f"{context} at {row_context}" if context else row_context
    return ValueError(f"{context}: {message}")


def parse_datetime(
    value: object, field_name: str | None = None, row_index: int | None = None
) -> datetime | None:
    if is_missing(value):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).strip().replace("/", "-"))
    except ValueError as exc:
        raise parse_error("must be a valid datetime", field_name, row_index) from exc


def parse_required_text(value: object, field_name: str) -> str:
    if is_missing(value):
        raise ValueError(f"{field_name} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def parse_quantity(value: object, field_name: str | None = None, row_index: int | None = None) -> int:
    if is_missing(value):
        raise parse_error("quantity is required", field_name, row_index)
    if isinstance(value, bool):
        raise parse_error("quantity must be an integer", field_name, row_index)

    try:
        quantity = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise parse_error("quantity must be an integer", field_name, row_index) from exc

    if not quantity.is_finite() or quantity != quantity.to_integral_value():
        raise parse_error("quantity must be an integer", field_name, row_index)
    return int(quantity)


def parse_optional_float(
    value: object, field_name: str | None = None, row_index: int | None = None
) -> float | None:
    if is_missing(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise parse_error("must be a number", field_name, row_index) from exc
    if not math.isfinite(number):
        raise parse_error("must be a finite number", field_name, row_index)
    return number


def parse_optional_text(value: object) -> str | None:
    if is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def normalize_order_rows(rows: list[Mapping[str, object]]) -> list[OrderLine]:
    normalized: list[OrderLine] = []
    for row_index, row in enumerate(rows):
        normalized.append(
            OrderLine(
                order_id=parse_required_text(row.get("order_id"), "order_id"),
                paid_time=parse_datetime(row.get("paid_time"), "paid_time", row_index),
                sku_id=parse_required_text(row.get("sku_id"), "sku_id"),
                quantity=parse_quantity(row.get("quantity", 1), "quantity", row_index),
                paid_amount=parse_optional_float(
                    row.get("paid_amount"), "paid_amount", row_index
                ),
                refund_status_optional=parse_optional_text(row.get("refund_status_optional")),
            )
        )
    return normalized
