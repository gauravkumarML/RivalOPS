import asyncio
import logging
from typing import List, Tuple

from sqlalchemy import func, select

from packages.core.db import get_session
from packages.core.langgraph_workflow import run_workflow_for_target
from packages.core.models import Run, Target


logger = logging.getLogger(__name__)


async def process_targets_once() -> None:
    """
    Run the workflow once for all enabled targets that are due.

    A target is due if it has no prior runs or its last run is older than
    target.schedule_minutes.
    """
    # Extract target IDs and URLs while session is open
    target_ids_and_urls: List[Tuple[int, str, str]] = []
    with get_session() as session:
        targets: List[Target] = (
            session.execute(select(Target).where(Target.enabled.is_(True))).scalars().all()
        )
        # Extract IDs, labels, and URLs before session closes
        for t in targets:
            target_ids_and_urls.append((t.id, t.label, t.url))

        # Map target_id -> last_run_started_at (if any)
        last_runs: List[Tuple[int, str]] = (
            session.execute(
                select(Run.target_id, func.max(Run.started_at)).group_by(Run.target_id)
            ).all()
        )
        last_run_map = {tid: started_at for tid, started_at in last_runs}

    if not target_ids_and_urls:
        logger.info("No enabled targets found")
        return

    logger.info("Running workflow for %s targets", len(target_ids_and_urls))
    for target_id, label, url in target_ids_and_urls:
        try:
            logger.info("=" * 60)
            logger.info("Processing target %s: %s", target_id, label)
            logger.info("URL: %s", url)
            logger.info("=" * 60)
            await run_workflow_for_target(target_id)
            logger.info("Completed processing target %s: %s", target_id, label)
        except Exception:
            logger.exception("Error running workflow for target %s (%s)", target_id, label)


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
