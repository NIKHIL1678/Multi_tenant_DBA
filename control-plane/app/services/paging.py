"""Keyset ("seek") pagination helpers for service queries. See app/api/pagination.py for why."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, literal, tuple_


def after_position(
    columns: Sequence[Any], position: Sequence[Any], *, descending: bool = False
) -> ColumnElement[bool]:
    """WHERE clause for "rows after this position" in ORDER BY columns (all asc or all desc).

    `columns` are model attributes or SQL expressions; each position value is bound with the
    column's own type (so e.g. CITEXT emails compare the same way the ORDER BY sorts them).
    """
    row = tuple_(*columns)
    point = tuple_(*(literal(v, type_=c.type) for c, v in zip(columns, position, strict=True)))
    return row < point if descending else row > point


def page_of[T](rows: list[T], limit: int) -> tuple[list[T], bool]:
    """Callers fetch limit + 1 rows: the extra one only tells us whether another page exists."""
    return rows[:limit], len(rows) > limit