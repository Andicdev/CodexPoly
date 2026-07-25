from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from cbr_trading.domain import RepriceOnTickChange
from cbr_trading.earnings import (
    EarningsDocumentCandidate,
    EarningsFactCandidate,
    EarningsMarketRule,
    EarningsMetric,
    EarningsProvider,
    EpsBasis,
    SourceAuthority,
    SqlAlchemyEarningsStore,
    earnings_scope_id,
)
from cbr_trading.execution import DryRunPreparedExecutor
from cbr_trading.orchestration import (
    ResolutionExecutionProfile,
    SqlAlchemyResolutionProfileStore,
)
from cbr_trading.resolution_hosted import (
    EarningsHostedResolutionWorker,
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.secret_guard import redact_exception
from cbr_trading.sources.earnings import EARNINGS_SOURCE_NAME


_SMOKE_PREFIX = "staging-smoke-"
_CONFIRMATION = "STAGING_SHADOW"


@dataclass(frozen=True)
class _SmokeFixture:
    run_id: str
    rule: EarningsMarketRule
    profile: ResolutionExecutionProfile
    source: EarningsDocumentCandidate
    fact: EarningsFactCandidate


class _RecordingDryRunExecutor:
    """Record aggregate smoke evidence while always delegating to dry-run."""

    def __init__(self) -> None:
        self._delegate = DryRunPreparedExecutor()
        self.prepared_template_ids: tuple[str, ...] = ()
        self.intents: tuple[Any, ...] = ()
        self.results: tuple[Any, ...] = ()

    def prepare(
        self,
        templates: Sequence[Any],
        *,
        context: Any,
    ) -> Any:
        rows = tuple(templates)
        self.prepared_template_ids = tuple(
            template.template_id for template in rows
        )
        return self._delegate.prepare(rows, context=context)

    def execute(
        self,
        intents: Sequence[Any],
        *,
        signal: Any,
    ) -> tuple[Any, ...]:
        self.intents = tuple(intents)
        self.results = tuple(
            self._delegate.execute(self.intents, signal=signal)
        )
        return self.results

    def close(self) -> None:
        self._delegate.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings: HostedResolutionSettings | None = None
    engine: Any | None = None
    earnings_store: SqlAlchemyEarningsStore | None = None
    profile_store: SqlAlchemyResolutionProfileStore | None = None
    worker: EarningsHostedResolutionWorker | None = None
    fixture: _SmokeFixture | None = None
    fixture_finalized = False
    payload: dict[str, Any] | None = None
    failure: str | None = None
    try:
        settings = HostedResolutionSettings.from_env(os.environ)
        guard_error = _staging_guard_error(
            args=args,
            settings=settings,
            environ=os.environ,
        )
        if guard_error is not None:
            raise ValueError(guard_error)

        from sqlalchemy import create_engine

        engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_reset_on_return="rollback",
            hide_parameters=True,
        )
        _retire_stale_fixtures(engine)
        fixture = _build_fixture(
            run_id=args.run_id or _new_run_id(),
            now=datetime.now(timezone.utc),
            eps=args.eps,
        )
        earnings_store = SqlAlchemyEarningsStore(
            database_url=settings.database_url
        )
        profile_store = SqlAlchemyResolutionProfileStore(
            database_url=settings.database_url
        )
        _persist_fixture(
            fixture,
            earnings_store=earnings_store,
            profile_store=profile_store,
        )

        recorder = _RecordingDryRunExecutor()
        worker = EarningsHostedResolutionWorker(
            settings=settings,
            earnings_store=earnings_store,
            profile_store=profile_store,
            executor_factory=lambda _profile: recorder,
        )
        preparations = worker.prepare()
        result = worker.poll_once()
        payload = _success_payload(
            fixture=fixture,
            recorder=recorder,
            preparations=preparations,
            result=result,
        )
    except Exception as exc:
        failure = redact_exception(exc)
    finally:
        if worker is not None:
            try:
                worker.close()
            except Exception:
                if failure is None:
                    failure = "RuntimeError"
        if fixture is not None and engine is not None:
            try:
                _finalize_fixture(engine, fixture)
                fixture_finalized = True
            except Exception as exc:
                if failure is None:
                    failure = (
                        "Smoke fixture finalization failed: "
                        f"{type(exc).__name__}"
                    )
        if profile_store is not None:
            profile_store.close()
        if earnings_store is not None:
            earnings_store.close()
        if engine is not None:
            engine.dispose()

    if failure is not None or payload is None:
        _print_json(
            {
                "ok": False,
                "mode": "staging_earnings_shadow",
                "error": failure or "smoke did not produce a result",
                "fixture_finalized": fixture_finalized,
                "order_submitted": False,
            },
            stream=sys.stderr,
        )
        return 5

    payload["fixture_finalized"] = fixture_finalized
    payload["ok"] = bool(payload["ok"] and fixture_finalized)
    _print_json(
        payload,
        stream=sys.stdout if payload["ok"] else sys.stderr,
    )
    return 0 if payload["ok"] else 5


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one staging-only hosted earnings shadow signal from a "
            "persisted synthetic fact through DryRunPreparedExecutor."
        )
    )
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"Required literal confirmation: {_CONFIRMATION}.",
    )
    parser.add_argument(
        "--eps",
        type=Decimal,
        default=Decimal("1.25"),
        help="Synthetic normalized EPS; defaults to a YES result.",
    )
    parser.add_argument("--run-id")
    return parser


def _staging_guard_error(
    *,
    args: argparse.Namespace,
    settings: HostedResolutionSettings,
    environ: Mapping[str, str],
) -> str | None:
    if args.confirm != _CONFIRMATION:
        return "explicit STAGING_SHADOW confirmation is required"
    if str(environ.get("CODEXPOLY_ENVIRONMENT") or "").strip().lower() != (
        "staging"
    ):
        return "CODEXPOLY_ENVIRONMENT must be staging"
    if settings.mode is not HostedResolutionMode.SHADOW:
        return "smoke runner requires shadow mode"
    if settings.supervision_enabled:
        return "smoke runner forbids order supervision"
    if _is_enabled(environ.get("CBR_LIVE_TRADING_ENABLED")):
        return "smoke runner forbids live trading"
    if not settings.database_url:
        return "staging database is not configured"
    try:
        from sqlalchemy.engine import make_url

        database = make_url(settings.database_url)
    except Exception:
        return "staging database configuration is invalid"
    if (
        str(database.host or "").casefold() != "postgres"
        or str(database.database or "") != "codexpoly"
        or str(database.username or "") != "codexpoly_app"
    ):
        return "smoke runner requires the isolated internal staging database"
    if not args.eps.is_finite():
        return "synthetic EPS must be finite"
    if args.run_id and not _safe_run_id(args.run_id):
        return "run id must contain 3-48 safe characters"
    return None


def _build_fixture(
    *,
    run_id: str,
    now: datetime,
    eps: Decimal,
) -> _SmokeFixture:
    suffix = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:10]
    ticker = f"SMK{suffix[:5].upper()}"
    scope_id = earnings_scope_id(ticker, 2099, 1)
    rule_key = f"{_SMOKE_PREFIX}{run_id}"
    condition_id = "0x" + hashlib.sha256(
        f"condition:{run_id}".encode("utf-8")
    ).hexdigest()
    source_url = (
        f"https://synthetic.invalid/codexpoly/staging/{run_id}"
    )
    fingerprint = hashlib.sha256(
        f"document:{run_id}".encode("utf-8")
    ).hexdigest()
    rule = EarningsMarketRule(
        rule_key=rule_key,
        scope_id=scope_id,
        ticker=ticker,
        cik=f"99{int(suffix[:8], 16):08d}"[-10:],
        fiscal_year=2099,
        fiscal_quarter=1,
        period_end=datetime(2099, 3, 31).date(),
        estimated_release_at=now,
        metric=EarningsMetric.NON_GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("1.00"),
        rounding_places=2,
        currency="USD",
        market_slug=rule_key,
        condition_id=condition_id,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "staging_smoke": True,
        },
        fallback_policy={"staging_smoke": True},
    )
    source = EarningsDocumentCandidate(
        scope_id=scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id=rule_key,
        ticker=ticker,
        cik=rule.cik,
        form_type="8-K",
        items=("2.02",),
        document_type="EX-99.1",
        source_url=source_url,
        filing_url=source_url,
        filed_at=now,
        received_at=now,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint=fingerprint,
        metadata={
            "parser_bypassed": True,
            "staging_smoke": True,
        },
    )
    normalized_eps = eps.quantize(Decimal("0.01"))
    fact = EarningsFactCandidate(
        scope_id=scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id=rule_key,
        ticker=ticker,
        cik=rule.cik,
        period_end=rule.period_end,
        metric=rule.metric,
        basis=rule.primary_basis,
        currency=rule.currency,
        raw_value=eps,
        value=normalized_eps,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        source_url=source_url,
        filing_url=source_url,
        published_at=now,
        detected_at=now,
        parser_name="staging_synthetic_parser_bypass",
        parser_version="1",
        confidence=Decimal("1"),
        document_fingerprint=fingerprint,
        evidence_title="Staging synthetic earnings fact",
        excerpt="Synthetic normalized EPS; parser bypassed.",
        attributes={
            "parser_bypassed": True,
            "staging_smoke": True,
        },
    )
    profile = ResolutionExecutionProfile(
        profile_key=rule_key,
        scope_id=scope_id,
        source_name=EARNINGS_SOURCE_NAME,
        source_reference=source_url,
        account_name="abccbaq",
        condition_id=condition_id,
        yes_desired_price=Decimal("0.999"),
        no_desired_price=Decimal("0.999"),
        quantity=Decimal("50"),
        prepare_from=now - timedelta(minutes=5),
        expires_at=now + timedelta(minutes=15),
        lifecycle_policy=RepriceOnTickChange(
            old_tick=Decimal("0.01"),
            new_tick=Decimal("0.001"),
            max_reprices=1,
        ),
        metadata={
            "rule_key": rule_key,
            "ticker": ticker,
            "staging_smoke": True,
        },
    )
    return _SmokeFixture(
        run_id=run_id,
        rule=rule,
        profile=profile,
        source=source,
        fact=fact,
    )


def _persist_fixture(
    fixture: _SmokeFixture,
    *,
    earnings_store: SqlAlchemyEarningsStore,
    profile_store: SqlAlchemyResolutionProfileStore,
) -> None:
    earnings_store.ensure_ready()
    profile_store.ensure_ready()
    earnings_store.save_shadow_rule(fixture.rule)
    source_record = earnings_store.record_source_event(fixture.source)
    earnings_store.update_source_event_status(
        source_record.row_id,
        status="PARSED",
    )
    earnings_store.record_fact(
        source_event_id=source_record.row_id,
        candidate=fixture.fact,
        reason="staging_synthetic_parser_bypass",
    )
    profile_store.save(fixture.profile)
    profile_store.set_enabled(
        fixture.profile.profile_key,
        enabled=True,
    )


def _retire_stale_fixtures(engine: Any) -> None:
    from sqlalchemy import text

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE resolution_execution_profiles
                SET status = 'DISABLED', updated_at = now()
                WHERE profile_key LIKE :prefix
                """
            ),
            {"prefix": f"{_SMOKE_PREFIX}%"},
        )
        connection.execute(
            text(
                """
                UPDATE earnings_market_rules
                SET status = 'DISABLED', updated_at = now()
                WHERE rule_key LIKE :prefix
                """
            ),
            {"prefix": f"{_SMOKE_PREFIX}%"},
        )
        connection.execute(
            text(
                """
                UPDATE earnings_fact_candidates AS fact
                SET status = 'SUPERSEDED', updated_at = now()
                FROM earnings_source_events AS event
                WHERE fact.source_event_id = event.id
                  AND event.provider_event_id LIKE :prefix
                  AND fact.status = 'VALIDATED'
                """
            ),
            {"prefix": f"{_SMOKE_PREFIX}%"},
        )


def _finalize_fixture(engine: Any, fixture: _SmokeFixture) -> None:
    from sqlalchemy import text

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE resolution_execution_profiles
                SET status = 'DISABLED', updated_at = now()
                WHERE profile_key = :profile_key
                """
            ),
            {"profile_key": fixture.profile.profile_key},
        )
        connection.execute(
            text(
                """
                UPDATE earnings_market_rules
                SET status = 'DISABLED', updated_at = now()
                WHERE rule_key = :rule_key
                """
            ),
            {"rule_key": fixture.rule.rule_key},
        )
        connection.execute(
            text(
                """
                UPDATE earnings_fact_candidates AS fact
                SET status = 'SUPERSEDED', updated_at = now()
                FROM earnings_source_events AS event
                WHERE fact.source_event_id = event.id
                  AND event.provider_event_id = :provider_event_id
                  AND fact.status = 'VALIDATED'
                """
            ),
            {"provider_event_id": fixture.source.provider_event_id},
        )


def _success_payload(
    *,
    fixture: _SmokeFixture,
    recorder: _RecordingDryRunExecutor,
    preparations: Sequence[Any],
    result: Any,
) -> dict[str, Any]:
    selected_outcomes = tuple(
        intent.outcome.value for intent in recorder.intents
    )
    statuses = tuple(row.status.value for row in recorder.results)
    not_attempted = all(
        not bool(row.attempted) for row in recorder.results
    )
    ok = (
        len(preparations) == 1
        and preparations[0].ready
        and len(recorder.prepared_template_ids) == 2
        and len(recorder.intents) == 1
        and selected_outcomes == ("YES",)
        and statuses == ("DRY_RUN",)
        and not_attempted
        and result.completed_count == 1
        and result.failed_count == 0
    )
    return {
        "ok": ok,
        "mode": "staging_earnings_shadow",
        "run_id": fixture.run_id,
        "parser_bypassed": True,
        "path": [
            "EarningsResolutionSource",
            "ResolutionSignal",
            "NumericThresholdStrategy",
            "OrderIntent",
            "DryRunPreparedExecutor",
        ],
        "prepared_template_count": len(
            recorder.prepared_template_ids
        ),
        "selected_intent_count": len(recorder.intents),
        "selected_outcomes": selected_outcomes,
        "execution_statuses": statuses,
        "completed_count": result.completed_count,
        "failed_count": result.failed_count,
        "order_submitted": not not_attempted,
    }


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _safe_run_id(value: str) -> bool:
    normalized = str(value or "").strip()
    return (
        3 <= len(normalized) <= 48
        and all(
            character.isalnum() or character in "._-"
            for character in normalized
        )
    )


def _is_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _print_json(
    payload: object,
    *,
    stream: object,
) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ),
        file=stream,
    )


if __name__ == "__main__":
    raise SystemExit(main())
