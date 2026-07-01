from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator


NonNegativeInt = Annotated[int, Field(ge=0)] | None
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)] | None
RequiredId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Note(BaseModel):
    note_id: RequiredId
    publish_time: datetime | None = None
    title: str | None = None
    body: str | None = None
    note_type: str | None = None
    cover_image_path: str | None = None
    impressions: NonNegativeInt = None
    reads: NonNegativeInt = None
    likes: NonNegativeInt = None
    collects: NonNegativeInt = None
    comments: NonNegativeInt = None
    shares: NonNegativeInt = None
    followers_gained: NonNegativeInt = None
    raw_file: str | None = None
    raw_row_id: str | None = None

    @field_validator(
        "impressions",
        "reads",
        "likes",
        "collects",
        "comments",
        "shares",
        "followers_gained",
    )
    @classmethod
    def non_negative_counts(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("count fields must be non-negative")
        return value


class Product(BaseModel):
    product_id: RequiredId
    product_name: str | None = None
    category: str | None = None
    vessel_type: str | None = None
    series: str | None = None
    color_family: str | None = None
    pattern_style: str | None = None
    price_band: str | None = None
    launch_date: date | None = None
    status: str | None = None


class Sku(BaseModel):
    sku_id: RequiredId
    product_id: str | None = None
    sku_name: str | None = None
    price: NonNegativeFloat = None
    inventory_optional: NonNegativeInt = None
    cost_optional: NonNegativeFloat = None


class OrderLine(BaseModel):
    order_id: RequiredId
    paid_time: datetime | None = None
    sku_id: RequiredId
    quantity: int = Field(default=1)
    paid_amount: NonNegativeFloat = None
    refund_status_optional: str | None = None

    @field_validator("quantity")
    @classmethod
    def positive_quantity(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("quantity must be positive")
        return value


class NoteSkuLink(BaseModel):
    note_id: RequiredId
    sku_id: RequiredId
    link_type: Literal["explicit", "manual", "inferred"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str | None = None
