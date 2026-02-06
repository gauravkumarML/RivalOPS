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
    with get_session() as session:
        targets: List[Target] = (
            session.execute(select(Target).where(Target.enabled.is_(True))).scalars().all()
        )

        # Map target_id -> last_run_started_at (if any)
        last_runs: List[Tuple[int, str]] = (
            session.execute(
                select(Run.target_id, func.max(Run.started_at)).group_by(Run.target_id)
            ).all()
        )
        last_run_map = {tid: started_at for tid, started_at in last_runs}

    if not targets:
        logger.info("No enabled targets found")
        return

    now = asyncio.get_event_loop().time()

    due_targets: List[Target] = []
    for t in targets:
        last_started = last_run_map.get(t.id)
        if not last_started:
            due_targets.append(t)
            continue
        # Simplified: use schedule_minutes as seconds threshold for prototype.
        # In a real system we'd compare datetimes; here we just always run.
        due_targets.append(t)

    if not due_targets:
        logger.info("No targets due for processing")
        return

    logger.info("Running workflow for %s targets", len(due_targets))
    for t in due_targets:
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
