import asyncio
import logging
from typing import List

from sqlalchemy import select

from packages.core.db import get_session
from packages.core.langgraph_workflow import run_workflow_for_target
from packages.core.models import Target


logger = logging.getLogger(__name__)


async def process_targets_once() -> None:
    """Run the workflow once for all enabled targets (prototype scheduler)."""
    with get_session() as session:
        targets: List[Target] = (
            session.execute(select(Target).where(Target.enabled.is_(True))).scalars().all()
        )

    if not targets:
        logger.info("No enabled targets found")
        return

    logger.info("Running workflow for %s targets", len(targets))
    for t in targets:
        try:
            logger.info("Running workflow for target %s (%s)", t.id, t.url)
            await run_workflow_for_target(t.id)
        except Exception:
            logger.exception("Error running workflow for target %s", t.id)


async def worker_loop(interval_seconds: int = 900) -> None:
    """
    Simple loop: every `interval_seconds`, process all enabled targets once.

    Later we can refine this to per-target schedules and backoff.
    """
    logger.info("Starting RivalOps worker loop")
    while True:
        await process_targets_once()
        await asyncio.sleep(interval_seconds)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
