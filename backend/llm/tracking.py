"""LLM invocation tracker — file + database audit trail."""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class LLMCallEntry:
    """Single record of an LLM API invocation."""
    timestamp: str
    provider: str
    model: str
    prompt: str
    response: str
    latency_ms: float
    tokens_used: int
    cost_usd: float
    related_market: Optional[str] = None
    call_type: str = "unknown"
    success: bool = True
    error: Optional[str] = None


class LLMTracker:
    """
    Comprehensive tracker for LLM API calls.
    Writes to JSONL files and optionally to the database.
    """

    PRICING = {
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
        "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
        "llama-3.1-70b-versatile": {"input": 0.59, "output": 0.79},
        "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
        "mixtral-8x7b-32768": {"input": 0.24, "output": 0.24},
    }

    def __init__(self, log_dir: str = "logs/ai", persist_to_db: bool = True):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._persist_to_db = persist_to_db
        self._log_file = self._log_dir / f"ai_calls_{datetime.now().strftime('%Y%m%d')}.jsonl"

    def estimate_cost(self, model: str, tokens_used: int) -> float:
        if model not in self.PRICING:
            return 0.0

        rates = self.PRICING[model]
        avg_rate = (rates["input"] + rates["output"]) / 2
        return (tokens_used / 1_000_000) * avg_rate

    def log_call(
        self,
        provider: str,
        model: str,
        prompt: str,
        response: str,
        latency_ms: float,
        tokens_used: int,
        related_market: Optional[str] = None,
        call_type: str = "unknown",
        success: bool = True,
        error: Optional[str] = None
    ) -> LLMCallEntry:
        cost = self.estimate_cost(model, tokens_used)

        entry = LLMCallEntry(
            timestamp=datetime.utcnow().isoformat(),
            provider=provider,
            model=model,
            prompt=prompt[:1000],
            response=response[:2000],
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            cost_usd=cost,
            related_market=related_market,
            call_type=call_type,
            success=success,
            error=error
        )

        self._append_to_file(entry)

        msg = (
            f"AI Call: {provider}/{model} | {call_type} | "
            f"{latency_ms:.0f}ms | {tokens_used} tokens | ${cost:.4f}"
        )
        if success:
            logger.debug(msg)
        else:
            logger.warning(f"{msg} | ERROR: {error}")

        return entry

    def _append_to_file(self, entry: LLMCallEntry):
        try:
            with open(self._log_file, "a") as f:
                f.write(json.dumps(asdict(entry)) + "\n")
        except Exception as exc:
            logger.error(f"Failed to write LLM log: {exc}")

    async def persist_to_database(self, entry: LLMCallEntry, session):
        if not self._persist_to_db:
            return

        try:
            from backend.storage.models import LLMLog

            row = LLMLog(
                timestamp=datetime.fromisoformat(entry.timestamp),
                provider=entry.provider,
                model=entry.model,
                prompt=entry.prompt,
                response=entry.response,
                latency_ms=entry.latency_ms,
                tokens_used=entry.tokens_used,
                cost_usd=entry.cost_usd,
                related_market=entry.related_market
            )
            session.add(row)
            session.commit()
        except Exception as exc:
            logger.error(f"Failed to persist LLM call to database: {exc}")

    def daily_summary(self) -> Dict[str, Any]:
        stats = {
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_latency_ms": 0.0,
            "by_provider": {},
            "by_call_type": {},
            "errors": 0
        }

        try:
            if not self._log_file.exists():
                return stats

            latencies = []
            with open(self._log_file, "r") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        stats["total_calls"] += 1
                        stats["total_tokens"] += rec.get("tokens_used", 0)
                        stats["total_cost_usd"] += rec.get("cost_usd", 0)
                        latencies.append(rec.get("latency_ms", 0))

                        if not rec.get("success", True):
                            stats["errors"] += 1

                        prov = rec.get("provider", "unknown")
                        if prov not in stats["by_provider"]:
                            stats["by_provider"][prov] = 0
                        stats["by_provider"][prov] += 1

                        ct = rec.get("call_type", "unknown")
                        if ct not in stats["by_call_type"]:
                            stats["by_call_type"][ct] = 0
                        stats["by_call_type"][ct] += 1

                    except json.JSONDecodeError:
                        continue

            if latencies:
                stats["avg_latency_ms"] = sum(latencies) / len(latencies)

        except Exception as exc:
            logger.error(f"Failed to compute daily LLM stats: {exc}")

        return stats


_tracker_instance: Optional[LLMTracker] = None


def get_tracker() -> LLMTracker:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = LLMTracker()
    return _tracker_instance
