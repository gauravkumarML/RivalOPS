from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    targets: Mapped[list["Target"]] = relationship("Target", back_populates="competitor")


class Target(Base):
    __tablename__ = "targets"
    __table_args__ = (UniqueConstraint("competitor_id", "url", name="uq_target_competitor_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    crawl_strategy: Mapped[str] = mapped_column(String(50), default="markdown", nullable=False)
    schedule_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    competitor: Mapped["Competitor"] = relationship("Competitor", back_populates="targets")
    snapshots: Mapped[list["Snapshot"]] = relationship("Snapshot", back_populates="target")
    runs: Mapped[list["Run"]] = relationship("Run", back_populates="target")


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("target_id", "content_hash", name="uq_snapshot_target_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    target: Mapped["Target"] = relationship("Target", back_populates="snapshots")
    runs: Mapped[list["Run"]] = relationship("Run", back_populates="snapshot")


class RunStatusEnum(str):
    SUCCESS = "success"
    NO_CHANGE = "no_change"
    DRIFT = "drift"
    ERROR = "error"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("targets.id"), nullable=False)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("snapshots.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RunStatusEnum.SUCCESS)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    target: Mapped["Target"] = relationship("Target", back_populates="runs")
    snapshot: Mapped["Snapshot"] = relationship("Snapshot", back_populates="runs")
    analyses: Mapped[list["Analysis"]] = relationship("Analysis", back_populates="run")
    briefing: Mapped["Briefing"] = relationship(
        "Briefing", back_populates="run", uselist=False
    )


class AnalysisDecisionEnum(str):
    NO_CHANGE = "no_change"
    DRIFT = "drift"


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    drift_score: Mapped[float] = mapped_column()
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    diff_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        CheckConstraint("drift_score >= 0.0 AND drift_score <= 1.0", name="ck_drift_score_range"),
    )

    run: Mapped["Run"] = relationship("Run", back_populates="analyses")


class ReviewStatusEnum(str):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Briefing(Base):
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    details_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReviewStatusEnum.PENDING
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    slack_ts: Mapped[str | None] = mapped_column(String(50), nullable=True)

    run: Mapped["Run"] = relationship("Run", back_populates="briefing")

