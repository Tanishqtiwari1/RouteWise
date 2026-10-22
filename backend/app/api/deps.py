from typing import Any

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


class PageParams:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200)):
        self.page = page
        self.page_size = page_size


def paginate(db: Session, stmt: Select, params: PageParams) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = list(db.scalars(stmt.offset((params.page - 1) * params.page_size).limit(params.page_size)))
    return rows, total


def apply_sort(stmt: Select, sort: str | None, allowed: dict[str, Any], default):
    if not sort:
        return stmt.order_by(default)
    desc = sort.startswith("-")
    col = allowed.get(sort.lstrip("-"))
    if col is None:
        return stmt.order_by(default)
    return stmt.order_by(col.desc() if desc else col.asc())
