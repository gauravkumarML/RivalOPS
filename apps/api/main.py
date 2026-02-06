from fastapi import Depends, FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
from sqlalchemy import select

from packages.core.db import get_session
from packages.core.models import Briefing, ReviewStatusEnum, Run, Target
from packages.core.slack_client import send_briefing_to_slack


def create_app() -> FastAPI:
    app = FastAPI(title="RivalOps API", version="0.1.0")
    templates = Jinja2Templates(directory="apps/api/templates")

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/review/queue", response_class=HTMLResponse)
    async def review_queue(request: Request):
        from packages.core.db import SessionLocal

        with get_session() as session:
            briefings = (
                session.execute(
                    select(Briefing)
                    .where(Briefing.review_status == ReviewStatusEnum.PENDING)
                    .order_by(Briefing.id.desc())
                )
                .scalars()
                .all()
            )
        return templates.TemplateResponse(
            "review_queue.html",
            {"request": request, "briefings": briefings},
        )

    @app.get("/review/{briefing_id}", response_class=HTMLResponse)
    async def review_detail(briefing_id: int, request: Request):
        with get_session() as session:
            briefing = session.get(Briefing, briefing_id)
            if not briefing:
                raise HTTPException(status_code=404, detail="Briefing not found")
            run: Run | None = session.get(Run, briefing.run_id)
            target: Target | None = session.get(Target, run.target_id) if run else None
        return templates.TemplateResponse(
            "review_detail.html",
            {"request": request, "briefing": briefing, "target": target},
        )

    @app.post("/review/{briefing_id}/approve")
    async def approve_briefing(
        briefing_id: int,
        request: Request,
        title: str = Form(...),
        executive_summary: str = Form(...),
        details_markdown: str = Form(...),
    ):
        with get_session() as session:
            briefing = session.get(Briefing, briefing_id)
            if not briefing:
                raise HTTPException(status_code=404, detail="Briefing not found")
            briefing.title = title
            briefing.executive_summary = executive_summary
            briefing.details_markdown = details_markdown
            briefing.review_status = ReviewStatusEnum.APPROVED
            # reviewer identity is not wired yet in v1
        # send to Slack (idempotent by slack_ts)
        await send_briefing_to_slack(briefing_id)
        return RedirectResponse(url="/review/queue", status_code=303)

    @app.post("/review/{briefing_id}/reject")
    async def reject_briefing(
        briefing_id: int,
        reason: str = Form(...),
    ):
        with get_session() as session:
            briefing = session.get(Briefing, briefing_id)
            if not briefing:
                raise HTTPException(status_code=404, detail="Briefing not found")
            briefing.review_status = ReviewStatusEnum.REJECTED
            # For prototype, store reason at end of details_markdown.
            briefing.details_markdown += f"\n\n---\n\n[REJECTED REASON]\n{reason}"
        return RedirectResponse(url="/review/queue", status_code=303)

    return app


app = create_app()
