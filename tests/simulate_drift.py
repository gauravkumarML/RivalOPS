import os
# Force SQLite for the simulation to avoid Postgres dependency
# Using path relative to this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(BASE_DIR, 'rivalops_test.db')}"


import asyncio
import logging
from unittest.mock import patch
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from packages.core.db import get_session, engine, Base
from packages.core.models import Competitor, Target, Briefing, Run, Snapshot, ReviewStatusEnum
from packages.core.langgraph_workflow import run_workflow_for_target
from packages.core.firecrawl_client import ScrapeResult

# Ensure tables exist for SQLite
Base.metadata.create_all(bind=engine)

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("simulate_drift")

# Mock data
CONTENT_V1 = """
# RivalCloud Pricing
Current Plan: Professional
Price: $50/month
Features:
- 10 Users
- 100GB Storage
- 24/7 Support
"""

CONTENT_V2 = """
# RivalCloud Pricing
Current Plan: Professional
Price: $75/month
Features:
- 10 Users
- 150GB Storage
- 24/7 Support
- AI Insights (NEW)
"""

async def simulate():
    # 1. Setup Mock Target
    with get_session() as session:
        # Check if mock competitor already exists
        competitor = session.query(Competitor).filter_by(name="MockCorp").first()
        if not competitor:
            competitor = Competitor(name="MockCorp", domain="mockcorp.com")
            session.add(competitor)
            session.flush()
        
        target = session.query(Target).filter_by(label="Pricing Page").first()
        if not target:
            target = Target(
                competitor_id=competitor.id,
                url="https://mockcorp.com/pricing",
                label="Pricing Page",
                schedule_minutes=60
            )
            session.add(target)
            session.flush()
        
        target_id = target.id
        logger.info(f"Using Target ID: {target_id}")

    # 2. Run Version A (Initial Snapshot)
    logger.info("--- Simulating Version A (No Changes) ---")
    mock_scrape_v1 = ScrapeResult(
        url="https://mockcorp.com/pricing",
        content_markdown=CONTENT_V1,
        metadata={"status_code": 200},
        content_hash="hash_v1"
    )

    with patch("packages.core.ingestion.scrape_url", return_value=mock_scrape_v1):
        await run_workflow_for_target(target_id)

    # 3. Run Version B (Drift Detected)
    logger.info("--- Simulating Version B (Price Increase) ---")
    mock_scrape_v2 = ScrapeResult(
        url="https://mockcorp.com/pricing",
        content_markdown=CONTENT_V2,
        metadata={"status_code": 200},
        content_hash="hash_v2"
    )

    with patch("packages.core.ingestion.scrape_url", return_value=mock_scrape_v2):
        state = await run_workflow_for_target(target_id)
        
    # 4. Verify results
    with get_session() as session:
        # State might be a dict or have dict-like access
        run_id = state.get("run_id") if isinstance(state, dict) else getattr(state, "run_id", None)
        briefing = session.query(Briefing).filter_by(run_id=run_id).first()
        if briefing:
            logger.info("✅ Briefing generated successfully!")
            logger.info(f"Title: {briefing.title}")
            logger.info(f"Risk Level: {briefing.risk_level}")
            logger.info(f"Review Status: {briefing.review_status}")
            logger.info("-" * 40)
            logger.info("Executive Summary:")
            logger.info(briefing.executive_summary)
        else:
            logger.error("❌ Failed to generate briefing. Check analysis logs.")

if __name__ == "__main__":
    asyncio.run(simulate())
