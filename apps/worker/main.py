import asyncio
import logging


logger = logging.getLogger(__name__)


async def worker_loop() -> None:
    """
    Placeholder worker loop.

    In later steps this will:
    - load targets from the database
    - trigger LangGraph runs for each target on a schedule
    """
    logger.info("Starting RivalOps worker loop (stub)")
    while True:
        logger.info("Worker heartbeat - no tasks implemented yet")
        await asyncio.sleep(30)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
