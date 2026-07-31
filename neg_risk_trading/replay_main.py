from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from uuid import UUID

from cbr_trading.secret_guard import redact_exception
from neg_risk_trading.domain import RouteDirection
from neg_risk_trading.replay import DeterministicReplay
from neg_risk_trading.repository import (
    SqlAlchemyObservationRepository,
)
from neg_risk_trading.settings import NegRiskRecorderSettings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay one append-only neg-risk shadow session "
            "without external market-data requests."
        )
    )
    parser.add_argument(
        "--session-id",
        type=UUID,
        help="Session UUID; defaults to the latest shadow session.",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        help="Optional positive prefix length for bounded diagnostics.",
    )
    parser.add_argument(
        "--quantities",
        help=(
            "Optional comma-separated positive quantities; "
            "defaults to the session contract."
        ),
    )
    parser.add_argument(
        "--directions",
        default="MAKER_BUY,MAKER_SELL",
        help="Comma-separated MAKER_BUY and/or MAKER_SELL.",
    )
    parser.add_argument(
        "--maximum-interval-ms",
        type=int,
        default=5_000,
        help="Cap used for time-weighted route statistics.",
    )
    return parser


def _quantities(value: str | None) -> tuple[Decimal, ...] | None:
    if value is None:
        return None
    try:
        result = tuple(
            Decimal(part.strip())
            for part in value.split(",")
            if part.strip()
        )
    except InvalidOperation as exc:
        raise ValueError("quantities_are_invalid") from exc
    if (
        not result
        or len(result) != len(set(result))
        or any(not item.is_finite() or item <= 0 for item in result)
    ):
        raise ValueError("quantities_are_invalid")
    return result


def _directions(value: str) -> tuple[RouteDirection, ...]:
    try:
        result = tuple(
            RouteDirection(part.strip().upper())
            for part in value.split(",")
            if part.strip()
        )
    except ValueError as exc:
        raise ValueError("directions_are_invalid") from exc
    if not result or len(result) != len(set(result)):
        raise ValueError("directions_are_invalid")
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repository: SqlAlchemyObservationRepository | None = None
    try:
        if args.max_messages is not None and args.max_messages <= 0:
            raise ValueError("max_messages_must_be_positive")
        if args.maximum_interval_ms <= 0:
            raise ValueError("maximum_interval_ms_must_be_positive")
        settings = NegRiskRecorderSettings.from_env()
        repository = SqlAlchemyObservationRepository(
            settings.database_url
        )
        repository.ensure_ready()
        session = repository.load_replay_session(
            session_id=args.session_id
        )
        replay = DeterministicReplay(
            session=session,
            quantities=_quantities(args.quantities),
            route_directions=_directions(args.directions),
            maximum_interval_ms=args.maximum_interval_ms,
        )
        result = replay.run(
            repository.iter_replay_messages(
                session_id=session.session_id,
                maximum_messages=args.max_messages,
            )
        )
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    except Exception as exc:
        print(
            "Neg-risk replay failed: "
            f"{redact_exception(exc)}",
            file=sys.stderr,
        )
        return 1
    finally:
        if repository is not None:
            repository.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
