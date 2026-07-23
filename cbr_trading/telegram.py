from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cbr_trading.client import DiscoveryResult
from cbr_trading.pipeline import PipelineOutcome


class TelegramError(RuntimeError):
    """Sanitized Telegram error that never includes the bot token."""


@dataclass(frozen=True)
class TelegramSendResult:
    ok: bool
    message_id: int | None = None


class TelegramNotifier:
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        timeout: float = 10.0,
        session: Any | None = None,
    ):
        token = str(bot_token or "").strip()
        target_chat = str(chat_id or "").strip()
        if not token:
            raise ValueError("bot_token is empty")
        if not target_chat:
            raise ValueError("chat_id is empty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")

        try:
            import requests
        except ImportError as exc:
            raise RuntimeError(
                "The 'requests' package is required for Telegram."
            ) from exc

        self._requests = requests
        self._bot_token = token
        self.chat_id = target_chat
        self.timeout = float(timeout)
        self._session = session or requests.Session()

    def __repr__(self) -> str:
        return (
            f"<TelegramNotifier chat_id={self.chat_id!r} "
            f"timeout={self.timeout!r}>"
        )

    def send_text(self, text: str) -> TelegramSendResult:
        message = str(text or "").strip()
        if not message:
            raise ValueError("Telegram message is empty")

        url = (
            "https://api.telegram.org/bot"
            f"{self._bot_token}/sendMessage"
        )
        try:
            response = self._session.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                },
                timeout=self.timeout,
            )
        except self._requests.RequestException as exc:
            raise TelegramError(
                f"Telegram request failed: {type(exc).__name__}"
            ) from exc

        data: dict[str, Any] = {}
        try:
            decoded = response.json()
            if isinstance(decoded, dict):
                data = decoded
        except Exception:
            data = {}

        if response.status_code != 200 or not data.get("ok"):
            description = str(data.get("description") or "").strip()
            safe_description = description[:200] or "no description"
            raise TelegramError(
                "Telegram send failed: "
                f"http={response.status_code} detail={safe_description}"
            )

        result = data.get("result")
        message_id = (
            result.get("message_id")
            if isinstance(result, dict)
            else None
        )
        return TelegramSendResult(
            ok=True,
            message_id=int(message_id) if message_id is not None else None,
        )

    def notify_release(
        self,
        release: DiscoveryResult,
        *,
        dry_run: bool,
    ) -> TelegramSendResult:
        return self.send_text(
            build_release_message(release, dry_run=dry_run)
        )

    def notify_pipeline(
        self,
        outcome: PipelineOutcome,
        *,
        dry_run: bool,
    ) -> TelegramSendResult:
        return self.send_text(
            build_pipeline_message(outcome, dry_run=dry_run)
        )


def build_release_message(
    release: DiscoveryResult,
    *,
    dry_run: bool,
) -> str:
    heading = (
        "DRY RUN — Bank of Russia release detected"
        if dry_run
        else "Bank of Russia release detected"
    )
    lines = [
        heading,
        f"New key rate: {release.new_rate}%",
        f"Title: {release.title}",
        f"URL: {release.url}",
    ]
    if dry_run:
        lines.append("No orders were sent.")
    return "\n".join(lines)


def build_pipeline_message(
    outcome: PipelineOutcome,
    *,
    dry_run: bool,
) -> str:
    heading = (
        "DRY RUN - Bank of Russia trading pipeline completed"
        if dry_run
        else "Bank of Russia trading pipeline completed"
    )
    previous_rate = (
        f"{outcome.previous_rate}%"
        if outcome.previous_rate is not None
        else "not configured"
    )
    change = (
        f"{outcome.change_bps:+g} bp ({outcome.direction})"
        if outcome.change_bps is not None
        else "not calculated"
    )
    lines = [
        heading,
        f"Previous key rate: {previous_rate}",
        f"New key rate: {outcome.release.new_rate}%",
        f"Change: {change}",
        f"Rules evaluated: {len(outcome.evaluations)}",
        f"Orders processed: {len(outcome.order_results)}",
    ]

    for result in outcome.order_results:
        intent = result.intent
        lines.append(
            "- "
            f"{result.status}: {intent.action} "
            f"qty={intent.quantity} price={intent.limit_price} "
            f"account={intent.account_name or '-'} "
            f"condition={intent.condition_id or '-'}"
        )

    if outcome.execution_error:
        lines.append(f"Order execution error: {outcome.execution_error}")
    if dry_run:
        lines.append("No live orders were sent.")
    lines.append(f"URL: {outcome.release.url}")
    return "\n".join(lines)
