"""Perplexity Agent API client — research-note enrichment only.

Off the trading hot path (orchestrator background task; never imported
by agents — same discipline as the Presto client, design §4.7). Skips
gracefully when PERPLEXITY_API_KEY is absent. ~$0.01 per enriched note
(fast-search preset: one web_search tool call + small completion).
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

API_URL = "https://api.perplexity.ai/v1/agent"

ASSET_NAMES = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana",
    "GLD": "gold", "SLV": "silver", "OIL-WTI": "WTI crude oil",
    "CORP-IG": "investment-grade corporate bonds",
    "CORP-HY": "high-yield corporate bonds", "UST-10Y": "10-year US Treasuries",
}


class PerplexityClient:
    def __init__(self) -> None:
        self.key = os.environ.get("PERPLEXITY_API_KEY", "")
        self._http: Optional[httpx.AsyncClient] = None

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    async def enrich(self, ticker: str, asset_class: str) -> Optional[str]:
        """Two plain-language sentences of current market context, or None."""
        if not self.enabled:
            return None
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=45.0)
        name = ASSET_NAMES.get(ticker, ticker)
        try:
            r = await self._http.post(
                API_URL,
                headers={"Authorization": f"Bearer {self.key}"},
                json={"preset": "fast-search",
                      "input": (f"Latest market-moving news for {name} "
                                f"({asset_class}). Maximum 2 short sentences, "
                                f"plain language for a retail investor, no "
                                f"citations or markdown."),
                      "max_output_tokens": 180})
            r.raise_for_status()
            d = r.json()
            for item in d.get("output", []):
                if item.get("type") == "message":
                    for c in item.get("content", []):
                        if c.get("type") == "output_text" and c.get("text"):
                            return c["text"].strip()
            return None
        except Exception:
            return None                      # enrichment is best-effort

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
