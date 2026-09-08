"""수집된 상품 + 점수화 결과."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

from autocpna.db import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String, unique=True)  # 쿠팡 상품 ID
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    price: Mapped[float] = mapped_column(Float)
    margin_rate: Mapped[float] = mapped_column(Float, default=0.0)
    search_volume: Mapped[float] = mapped_column(Float, default=0.0)
    trend_momentum: Mapped[float] = mapped_column(Float, default=0.0)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0.0)
    seasonality_fit: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    product_url: Mapped[str] = mapped_column(String, default="")
    image_url: Mapped[str] = mapped_column(String, default="")
    collected_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
