"""Persistence for the API (plan §M6).

SQLite via SQLModel — schema written Postgres-compatible so the swap is a connection string.
The whole assembled `ClaimFile` graph is stored as JSON on the claim row; that is what the
dashboard renders and what corrections are applied to. Reviewer corrections are additionally
logged to their own table as training data.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Engine
from sqlmodel import Field, SQLModel, create_engine


class ClaimRow(SQLModel, table=True):
    __tablename__ = "claims"

    id: str = Field(primary_key=True)
    status: str = "processing"
    claim_type: str = "cashless_hospitalization"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    graph: str = "{}"  # ClaimFile serialized to JSON


class CorrectionRow(SQLModel, table=True):
    __tablename__ = "corrections"

    id: int | None = Field(default=None, primary_key=True)
    claim_id: str = Field(index=True)
    document_id: str
    field_path: str
    old_value: str | None = None
    new_value: str | None = None
    reviewer: str | None = None
    at: datetime = Field(default_factory=datetime.utcnow)


def make_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
