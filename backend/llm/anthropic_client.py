"""Anthropic Claude integration for deep market analysis."""
import time
from typing import Optional, List, Dict, Any
import logging

from .types import (
    LLMResult, AnomalyFlag, PositionAdvice, BaseLLMClient,
    build_signal_prompt
)
from .tracking import get_tracker

logger = logging.getLogger(__name__)


class AnthropicEngine(BaseLLMClient):
    """
    Claude-powered engine for deep signal reasoning,
    trade decision analysis, and anomaly detection.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514"):
        self._api_key = api_key
        self._model = model
        self._handle = None

    def _init_client(self):
        if self._handle is None:
            if not self._api_key:
                from backend.env import cfg
                self._api_key = cfg.ANTHROPIC_API_KEY

            if not self._api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured")

            try:
                import anthropic
                self._handle = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                raise ImportError("anthropic package not installed. Run: pip install anthropic")

        return self._handle

    async def analyze_signal(
        self,
        signal_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> LLMResult:
        t0 = time.time()

        try:
            client = self._init_client()
            prompt = build_signal_prompt(signal_data, context)

            message = client.messages.create(
                model=self._model,
                max_tokens=500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            text = message.content[0].text
            tok = message.usage.input_tokens + message.usage.output_tokens
            elapsed = (time.time() - t0) * 1000

            tracker = get_tracker()
            entry = tracker.log_call(
                provider="claude",
                model=self._model,
                prompt=prompt,
                response=text,
                latency_ms=elapsed,
                tokens_used=tok,
                related_market=signal_data.get('market_ticker'),
                call_type="analysis",
                success=True
            )
            try:
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
            except Exception as db_err:
                logger.debug(f"DB logging skipped: {db_err}")

            conf = 0.7
            if "high confidence" in text.lower():
                conf = 0.85
            elif "low confidence" in text.lower():
                conf = 0.4
            elif "uncertain" in text.lower():
                conf = 0.5

            risks = []
            if "risk" in text.lower():
                risks = ["Market volatility", "Model uncertainty"]

            return LLMResult(
                reasoning=text,
                confidence=conf,
                recommendation=None,
                risk_factors=risks,
                raw_response=text,
                model_used=self._model,
                provider="claude",
                latency_ms=elapsed,
                tokens_used=tok
            )

        except Exception as exc:
            logger.error(f"Claude analysis failed: {exc}")
            elapsed = (time.time() - t0) * 1000

            try:
                tracker = get_tracker()
                entry = tracker.log_call(
                    provider="claude",
                    model=self._model,
                    prompt="",
                    response="",
                    latency_ms=elapsed,
                    tokens_used=0,
                    related_market=signal_data.get('market_ticker'),
                    call_type="analysis",
                    success=False,
                    error=str(exc)
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
                        tokens_used=0,
                        cost_usd=0,
                        success=False,
                        related_market=entry.related_market
                    )
                    session.add(row)
                    session.commit()
                finally:
                    session.close()
            except Exception:
                pass

            return LLMResult(
                reasoning=f"Analysis unavailable: {str(exc)}",
                confidence=0.0,
                raw_response="",
                model_used=self._model,
                provider="claude",
                latency_ms=elapsed,
                tokens_used=0
            )

    async def classify_market(
        self,
        title: str,
        description: str = ""
    ) -> tuple[str, float]:
        t0 = time.time()
        try:
            client = self._init_client()

            prompt = f"""Classify this prediction market. Respond with ONLY the category name.

Title: {title}

Categories: weather, crypto, politics, economics, sports, other"""

            message = client.messages.create(
                model=self._model,
                max_tokens=50,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            text = message.content[0].text.strip().lower()
            tok = message.usage.input_tokens + message.usage.output_tokens
            elapsed = (time.time() - t0) * 1000

            try:
                tracker = get_tracker()
                entry = tracker.log_call(
                    provider="claude",
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

            valid = ["weather", "crypto", "politics", "economics", "sports", "other"]
            for cat in valid:
                if cat in text:
                    return (cat, 0.8)

            return ("other", 0.5)

        except Exception as exc:
            logger.error(f"Claude classification failed: {exc}")
            return ("other", 0.0)

    async def detect_anomalies(
        self,
        markets: List[Dict[str, Any]]
    ) -> List[AnomalyFlag]:
        if not markets:
            return []

        try:
            client = self._init_client()

            summary = "\n".join([
                f"- {m.get('ticker', 'Unknown')}: ${m.get('yes_price', 0):.2f} YES, "
                f"${m.get('volume', 0):,.0f} volume"
                for m in markets[:20]
            ])

            prompt = f"""Analyze these prediction markets for anomalies:

{summary}

Look for:
1. Unusual price movements (far from 0.5)
2. Very low or very high volume compared to peers
3. Prices that seem mispriced based on the market title

List any anomalies found. If none, say "No anomalies detected."
Be concise (1-2 sentences per anomaly)."""

            message = client.messages.create(
                model=self._model,
                max_tokens=500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            text = message.content[0].text

            flags = []
            if "no anomalies" not in text.lower():
                for line in text.split("\n"):
                    if line.strip() and any(m.get('ticker', '') in line for m in markets):
                        flags.append(AnomalyFlag(
                            market_ticker=line.split(":")[0].strip() if ":" in line else "Unknown",
                            anomaly_type="ai_detected",
                            severity="medium",
                            description=line.strip(),
                            ai_analysis=text
                        ))

            return flags

        except Exception as exc:
            logger.error(f"Claude anomaly detection failed: {exc}")
            return []

    async def evaluate_trade_decision(
        self,
        signal_data: Dict[str, Any],
        portfolio_state: Dict[str, Any]
    ) -> PositionAdvice:
        try:
            client = self._init_client()

            prompt = f"""Should we execute this trade?

Signal:
- Market: {signal_data.get('market_title', 'Unknown')}
- Direction: {signal_data.get('direction', 'Unknown')}
- Edge: {signal_data.get('edge', 0):.1%}
- Suggested Size: ${signal_data.get('suggested_size', 0):.2f}

Portfolio:
- Bankroll: ${portfolio_state.get('bankroll', 0):,.2f}
- Current P&L: ${portfolio_state.get('total_pnl', 0):,.2f}
- Pending Trades: {portfolio_state.get('pending_trades', 0)}

Provide:
1. Should trade? (yes/no)
2. Recommended size adjustment (if any)
3. Key risks (bullet points)
4. Confidence (0-100)

Be concise."""

            message = client.messages.create(
                model=self._model,
                max_tokens=300,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            text = message.content[0].text

            execute = "yes" in text.lower()[:50]

            conf = 0.6
            import re
            conf_match = re.search(r'confidence[:\s]*(\d+)', text.lower())
            if conf_match:
                conf = int(conf_match.group(1)) / 100

            return PositionAdvice(
                signal_ticker=signal_data.get('market_ticker', ''),
                should_trade=execute,
                recommended_size=signal_data.get('suggested_size'),
                reasoning=text,
                risk_assessment="See reasoning",
                confidence=conf,
                caveats=[]
            )

        except Exception as exc:
            logger.error(f"Claude trade analysis failed: {exc}")
            return PositionAdvice(
                signal_ticker=signal_data.get('market_ticker', ''),
                should_trade=True,
                reasoning=f"AI analysis unavailable: {exc}",
                confidence=0.5
            )
