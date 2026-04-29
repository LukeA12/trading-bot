"""Groq LLM integration for fast classification and lightweight analysis."""
import time
import re
from typing import Optional, Dict, Any, List
import logging

from .types import LLMResult, BaseLLMClient, build_classification_prompt
from .tracking import get_tracker

logger = logging.getLogger(__name__)


class GroqEngine(BaseLLMClient):
    """
    Groq-powered engine for rapid market categorization,
    title parsing, and lightweight signal analysis.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "llama-3.1-70b-versatile"):
        self._api_key = api_key
        self._model = model
        self._handle = None

    def _init_client(self):
        if self._handle is None:
            if not self._api_key:
                from backend.env import cfg
                self._api_key = cfg.GROQ_API_KEY

            if not self._api_key:
                raise ValueError("GROQ_API_KEY not configured")

            try:
                from groq import Groq
                self._handle = Groq(api_key=self._api_key)
            except ImportError:
                raise ImportError("groq package not installed. Run: pip install groq")

        return self._handle

    async def classify_market(
        self,
        title: str,
        description: str = ""
    ) -> tuple[str, float]:
        t0 = time.time()

        try:
            client = self._init_client()
            prompt = build_classification_prompt(title, description)

            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=20,
                temperature=0.1
            )

            text = resp.choices[0].message.content.strip().lower()
            elapsed = (time.time() - t0) * 1000
            tok = resp.usage.total_tokens if resp.usage else 0

            logger.debug(f"Groq classification: '{title[:30]}...' -> {text} ({elapsed:.0f}ms)")

            try:
                tracker = get_tracker()
                entry = tracker.log_call(
                    provider="groq",
                    model=self._model,
                    prompt=prompt,
                    response=text,
                    latency_ms=elapsed,
                    tokens_used=tok,
                    call_type="classification",
                    success=True
                )
                from backend.storage.models import DbSession, LLMLog
                from datetime import datetime
                session = DbSession()
                try:
                    row = LLMLog(
                        timestamp=datetime.fromisoformat(entry.timestamp),
                        provider=entry.provider,
                        model=entry.model,
                        call_type=entry.call_type,
                        latency_ms=entry.latency_ms,
                        tokens_used=entry.tokens_used,
                        cost_usd=entry.cost_usd,
                        success=True
                    )
                    session.add(row)
                    session.commit()
                finally:
                    session.close()
            except Exception:
                pass

            parts = text.split(",")
            category = parts[0].strip()
            conf = 0.7

            if len(parts) > 1:
                try:
                    conf = int(parts[1].strip()) / 100
                except ValueError:
                    pass

            valid = ["weather", "crypto", "politics", "economics", "sports", "other"]
            if category not in valid:
                for cat in valid:
                    if cat in text:
                        category = cat
                        break
                else:
                    category = "other"

            return (category, min(1.0, max(0.0, conf)))

        except Exception as exc:
            logger.error(f"Groq classification failed: {exc}")
            return ("other", 0.0)

    async def extract_market_details(
        self,
        title: str
    ) -> Dict[str, Any]:
        t0 = time.time()

        try:
            client = self._init_client()

            prompt = f"""Extract details from this prediction market title:

"{title}"

Respond in this exact format (use N/A if not found):
threshold: <number or N/A>
direction: <above/below/N/A>
asset: <asset name or N/A>
timeframe: <date/period or N/A>"""

            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,
                temperature=0.1
            )

            text = resp.choices[0].message.content.strip()
            elapsed = (time.time() - t0) * 1000

            logger.debug(f"Groq extraction ({elapsed:.0f}ms): {text[:50]}...")

            details: Dict[str, Any] = {
                "threshold": None,
                "direction": None,
                "asset": None,
                "timeframe": None
            }

            for line in text.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip()

                    if value.lower() != "n/a":
                        if key == "threshold":
                            num_match = re.search(r'[\d,\.]+', value)
                            if num_match:
                                try:
                                    details["threshold"] = float(num_match.group().replace(',', ''))
                                except ValueError:
                                    pass
                        elif key == "direction":
                            if "above" in value.lower():
                                details["direction"] = "above"
                            elif "below" in value.lower():
                                details["direction"] = "below"
                        elif key in details:
                            details[key] = value

            return details

        except Exception as exc:
            logger.error(f"Groq extraction failed: {exc}")
            return {
                "threshold": None,
                "direction": None,
                "asset": None,
                "timeframe": None
            }

    async def analyze_signal(
        self,
        signal_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> LLMResult:
        t0 = time.time()

        try:
            client = self._init_client()

            prompt = f"""Briefly analyze this trading signal (1-2 sentences):

Market: {signal_data.get('market_title', 'Unknown')}
Edge: {signal_data.get('edge', 0):.1%}
Direction: {signal_data.get('direction', 'Unknown')}

Key question: Is this edge reliable?"""

            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,
                temperature=0.3
            )

            text = resp.choices[0].message.content.strip()
            elapsed = (time.time() - t0) * 1000
            tok = resp.usage.total_tokens if resp.usage else 0

            try:
                tracker = get_tracker()
                entry = tracker.log_call(
                    provider="groq",
                    model=self._model,
                    prompt=prompt,
                    response=text,
                    latency_ms=elapsed,
                    tokens_used=tok,
                    related_market=signal_data.get('market_ticker'),
                    call_type="analysis",
                    success=True
                )
                from backend.storage.models import DbSession, LLMLog
                from datetime import datetime
                session = DbSession()
                try:
                    row = LLMLog(
                        timestamp=datetime.fromisoformat(entry.timestamp),
                        provider=entry.provider,
                        model=entry.model,
                        call_type=entry.call_type,
                        latency_ms=entry.latency_ms,
                        tokens_used=entry.tokens_used,
                        cost_usd=entry.cost_usd,
                        success=True,
                        related_market=entry.related_market
                    )
                    session.add(row)
                    session.commit()
                finally:
                    session.close()
            except Exception:
                pass

            conf = 0.6
            if "reliable" in text.lower() or "strong" in text.lower():
                conf = 0.75
            elif "uncertain" in text.lower() or "risky" in text.lower():
                conf = 0.4

            return LLMResult(
                reasoning=text,
                confidence=conf,
                raw_response=text,
                model_used=self._model,
                provider="groq",
                latency_ms=elapsed,
                tokens_used=tok
            )

        except Exception as exc:
            logger.error(f"Groq analysis failed: {exc}")
            return LLMResult(
                reasoning=f"Analysis unavailable: {exc}",
                confidence=0.0,
                model_used=self._model,
                provider="groq",
                latency_ms=(time.time() - t0) * 1000
            )

    async def detect_anomalies(
        self,
        markets: List[Dict[str, Any]]
    ) -> List:
        return []


async def classify_with_fallback(
    title: str,
    description: str = "",
    groq_engine: Optional[GroqEngine] = None
) -> tuple[str, float]:
    """
    Classify a market using Groq with keyword fallback.
    """
    if groq_engine:
        try:
            return await groq_engine.classify_market(title, description)
        except Exception as exc:
            logger.warning(f"Groq failed, using keyword fallback: {exc}")

    from backend.core.classifier import classify_market
    return classify_market(title, description)
