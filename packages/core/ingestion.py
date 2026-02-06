from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .firecrawl_client import ScrapeResult, scrape_url
from .models import Snapshot, Target


async def ingest_target(target_id: int, *, session: Optional[Session] = None) -> Snapshot:
    """
    Scrape a target URL via Firecrawl and persist a new Snapshot if content_hash is new.

    Returns the existing or newly created Snapshot.
    """
    own_session = False
    if session is None:
        own_session = True
        ctx = get_session()
        session = ctx.__enter__()  # type: ignore[assignment]

    try:
        target = session.get(Target, target_id)
        if not target:
            raise ValueError(f"Target {target_id} not found")

        scrape: ScrapeResult = await scrape_url(target.url)

        # Check idempotency: do we already have this hash for this target?
        existing_snapshot = session.execute(
            select(Snapshot).where(
                Snapshot.target_id == target.id, Snapshot.content_hash == scrape.content_hash
            )
        ).scalar_one_or_none()
        if existing_snapshot:
            return existing_snapshot

        snapshot = Snapshot(
            target_id=target.id,
            fetched_at=datetime.utcnow(),
            content_hash=scrape.content_hash,
            content_markdown=scrape.content_markdown,
            metadata_json=scrape.metadata,
        )
        session.add(snapshot)
        session.flush()
        return snapshot
    finally:
        if own_session:
            assert session is not None
            ctx.__exit__(None, None, None)  # type: ignore[name-defined]

