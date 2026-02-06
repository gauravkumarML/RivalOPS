from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from .config import settings


logger = logging.getLogger(__name__)


class FirecrawlError(Exception):
    """Raised when Firecrawl cannot return content successfully."""


@dataclass
class ScrapeResult:
    url: str
    content_markdown: str
    metadata: Dict[str, Any]
    content_hash: str


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def scrape_url(
    url: str,
    *,
    max_retries: int = 3,
    backoff_seconds: float = 2.0,
    timeout: float = 30.0,
    client: Optional[httpx.AsyncClient] = None,
) -> ScrapeResult:
    """
    Scrape a URL using Firecrawl, with simple exponential backoff on 429/5xx.

    This assumes the Firecrawl API is exposed as:
      POST https://api.firecrawl.dev/v1/scrape
      body: { "url": "<url>", "format": "markdown" }
    """
    if not settings.firecrawl_api_key:
        raise FirecrawlError("FIRECRAWL_API_KEY is not set")

    headers = {
        "Authorization": f"Bearer {settings.firecrawl_api_key}",
        "Content-Type": "application/json",
    }
    payload = {"url": url, "format": "markdown"}

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)
        close_client = True

    try:
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = await client.post(
                    "https://api.firecrawl.dev/v1/scrape", json=payload, headers=headers
                )
            except httpx.HTTPError as exc:
                logger.warning("Firecrawl request error (attempt %s): %s", attempt, exc)
                if attempt >= max_retries:
                    raise FirecrawlError(f"HTTP error from Firecrawl after {attempt} attempts") from exc
            else:
                if resp.status_code == 200:
                    data = resp.json()
                    # The exact response schema may differ; keep this flexible.
                    content_md = data.get("markdown") or data.get("content") or ""
                    if not content_md:
                        raise FirecrawlError("Firecrawl returned empty content")
                    metadata = {
                        "status_code": resp.status_code,
                        "firecrawl_raw": data,
                    }
                    content_hash = _hash_content(content_md)
                    return ScrapeResult(
                        url=url,
                        content_markdown=content_md,
                        metadata=metadata,
                        content_hash=content_hash,
                    )

                if resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning(
                        "Firecrawl transient error %s on %s (attempt %s)",
                        resp.status_code,
                        url,
                        attempt,
                    )
                    if attempt >= max_retries:
                        raise FirecrawlError(
                            f"Firecrawl transient errors after {attempt} attempts, last code "
                            f"{resp.status_code}"
                        )
                    # simple exponential backoff
                    await httpx.AsyncClient().aclose()  # no-op; keep awaitable
                else:
                    raise FirecrawlError(
                        f"Firecrawl returned non-success status {resp.status_code}: {resp.text}"
                    )
    finally:
        if close_client:
            await client.aclose()

