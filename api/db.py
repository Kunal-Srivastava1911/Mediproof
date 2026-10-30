"""Persistence for the API (plan §M6).

SQLite via SQLModel — schema written Postgres-compatible so the swap is a connection string.
The whole assembled `ClaimFile` graph is stored as JSON on the claim row; that is what the
dashboard renders and what corrections are applied to. Reviewer corrections are additionally
logged to their own table as training data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Field, SQLModel, create_engine


def _utcnow() -> datetime:
    """Timezone-aware UTC now (SQLAlchemy 2.1+ rejects naive datetimes)."""
    return datetime.now(UTC)

class ClaimRow(SQLModel, table=True):
    __tablename__ = "claims"

    id: str = Field(primary_key=True)
    status: str = "processing"
    claim_type: str = "cashless_hospitalization"
    created_at: datetime = Field(default_factory=_utcnow)
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
    at: datetime = Field(default_factory=_utcnow)


class FindingDecisionRow(SQLModel, table=True):
    """A reviewer's confirm / dismiss / promote on one review item — verifier training data."""

    __tablename__ = "finding_decisions"

    id: int | None = Field(default=None, primary_key=True)
    claim_id: str = Field(index=True)
    finding_id: str
    finding_type: str
    origin: str
    verifier_score: float | None = None
    decision: str
    reason: str | None = None
    promoted: bool = False
    reviewer: str | None = None
    at: datetime = Field(default_factory=_utcnow)


def make_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
        # data/ is gitignored, so a fresh clone has no folder for the SQLite file yet.
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
