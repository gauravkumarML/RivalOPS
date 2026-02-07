import os
# Force SQLite to use the simulated database
# Using path relative to this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(BASE_DIR, 'rivalops_test.db')}"


import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

from packages.core.db import get_session
from packages.core.models import Briefing
from packages.core.slack_client import send_briefing_to_slack

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_slack")

async def test_slack():
    with get_session() as session:
        # Get the most recent briefing
        briefing = session.query(Briefing).order_by(Briefing.id.desc()).first()
        if not briefing:
            logger.error("No briefing found in rivalops_test.db. Run simulate_drift.py first.")
            return
        
        briefing_id = briefing.id
        logger.info(f"Triggering Slack notification for Briefing ID: {briefing_id}")
        
        # Reset slack_ts so it actually sends if it was already "posted"
        briefing.slack_ts = None
        session.add(briefing)
        session.flush()

    # Call the core slack integration
    await send_briefing_to_slack(briefing_id)
    logger.info("Done!")

if __name__ == "__main__":
    asyncio.run(test_slack())
