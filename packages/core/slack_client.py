from __future__ import annotations

import json
import logging
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .models import Briefing, Run, Target


logger = logging.getLogger(__name__)


async def send_briefing_to_slack(briefing_id: int, *, session: Optional[Session] = None) -> None:
    """
    Post an approved briefing to Slack using an incoming webhook.

    Idempotent per briefing: if slack_ts is already set, do nothing.
    """
    if not settings.slack_webhook_url:
        logger.warning("SLACK_WEBHOOK_URL is not set; skipping Slack publish")
        return

    own_session = False
    if session is None:
        own_session = True
        ctx = get_session()
        session = ctx.__enter__()  # type: ignore[assignment]

    try:
        briefing = session.get(Briefing, briefing_id)
        if not briefing:
            raise ValueError(f"Briefing {briefing_id} not found")

        if briefing.slack_ts:
            logger.info("Briefing %s already posted to Slack (ts=%s)", briefing_id, briefing.slack_ts)
            return

        run: Run | None = session.get(Run, briefing.run_id)
        target: Target | None = session.get(Target, run.target_id) if run else None

        title = briefing.title
        summary = briefing.executive_summary
        details_link = f"{settings.base_url}/review/{briefing.id}"

        text = f"*RivalOps update*: {title}\n\n{summary}\n\n<{details_link}|Open in RivalOps>"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                settings.slack_webhook_url,
                content=json.dumps({"text": text}),
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )
        if resp.status_code >= 300:
            logger.error(
                "Slack webhook failed for briefing %s: %s %s",
                briefing_id,
                resp.status_code,
                resp.text,
            )
            return

        # Incoming webhooks don't return ts by default; we just mark a flag.
        briefing.slack_ts = "posted"
        session.add(briefing)
    finally:
        if own_session:
            assert session is not None
            ctx.__exit__(None, None, None)  # type: ignore[name-defined]

