from collections.abc import Mapping
from datetime import datetime

from xhs_ceramics_analytics.contracts.schemas import OrderLine


def parse_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("/", "-"))


def normalize_order_rows(rows: list[Mapping[str, object]]) -> list[OrderLine]:
    normalized: list[OrderLine] = []
    for row in rows:
        normalized.append(
            OrderLine(
                order_id=str(row["order_id"]),
                paid_time=parse_datetime(row.get("paid_time")),
                sku_id=str(row["sku_id"]),
                quantity=int(float(row.get("quantity", 1))),
                paid_amount=float(row["paid_amount"])
                if row.get("paid_amount") not in (None, "")
                else None,
                refund_status_optional=(
                    str(row["refund_status_optional"])
                    if row.get("refund_status_optional") not in (None, "")
                    else None
                ),
            )
        )
    return normalized
