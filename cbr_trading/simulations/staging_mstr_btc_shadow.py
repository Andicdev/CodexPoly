from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from cbr_trading.domain import RepriceOnTickChange
from cbr_trading.execution import DryRunPreparedExecutor
from cbr_trading.mstr_btc import (
    MSTR_JUL21_27_WINDOW_START,
    MstrBtcActivity,
    MstrBtcAuditStatus,
    MstrBtcDocumentCandidate,
    MstrBtcFactCandidate,
    MstrBtcHoldingsBaseline,
    MstrBtcMarketBinding,
    MstrBtcProvider,
    MstrBtcResolutionRule,
    MstrBtcValueDerivation,
    SqlAlchemyMstrBtcAuditStore,
    SqlAlchemyMstrBtcHoldingsStore,
)
from cbr_trading.orchestration import (
    ResolutionExecutionProfile,
    SqlAlchemyResolutionProfileStore,
)
from cbr_trading.resolution_hosted import (
    HostedResolutionMode,
    HostedResolutionSettings,
    MstrBtcHostedResolutionWorker,
)
from cbr_trading.secret_guard import redact_exception
from cbr_trading.sources import MSTR_BTC_SOURCE_NAME


_CONFIRMATION = "STAGING_MSTR_SHADOW"
_SMOKE_PREFIX = "staging-mstr-smoke-"
_RUN_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{2,47}$"
)


@dataclass(frozen=True)
class _SmokeFixture:
    run_id: str
    weekly_scope_id: str
    rules: tuple[MstrBtcResolutionRule, ...]
    bindings: tuple[MstrBtcMarketBinding, ...]
    event: MstrBtcDocumentCandidate
    fact: MstrBtcFactCandidate
    profiles: tuple[ResolutionExecutionProfile, ...]


class _RecordingDryRunExecutor:
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
            row.template_id for row in rows
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
    holdings_store: SqlAlchemyMstrBtcHoldingsStore | None = None
    audit_store: SqlAlchemyMstrBtcAuditStore | None = None
    profile_store: SqlAlchemyResolutionProfileStore | None = None
    worker: MstrBtcHostedResolutionWorker | None = None
    saved_profile_keys: list[str] = []
    profiles_disabled = False
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
        _retire_stale_profiles(engine)
        holdings_store = SqlAlchemyMstrBtcHoldingsStore(
            database_url=settings.database_url,
        )
        audit_store = SqlAlchemyMstrBtcAuditStore(
            database_url=settings.database_url,
        )
        profile_store = SqlAlchemyResolutionProfileStore(
            database_url=settings.database_url,
        )
        holdings_store.ensure_ready()
        audit_store.ensure_ready()
        profile_store.ensure_ready()
        baseline = holdings_store.pin_baseline(
            before=MSTR_JUL21_27_WINDOW_START,
        )
        fixture = _build_fixture(
            run_id=args.run_id or _new_run_id(),
            now=datetime.now(timezone.utc),
            baseline=baseline,
        )
        _persist_fixture(
            fixture,
            audit_store=audit_store,
            profile_store=profile_store,
            saved_profile_keys=saved_profile_keys,
        )

        recorders: dict[str, _RecordingDryRunExecutor] = {}

        def executor_factory(
            profile: ResolutionExecutionProfile,
        ) -> _RecordingDryRunExecutor:
            recorder = _RecordingDryRunExecutor()
            recorders[profile.profile_key] = recorder
            return recorder

        worker = MstrBtcHostedResolutionWorker(
            settings=settings,
            audit_store=audit_store,
            profile_store=profile_store,
            rules=fixture.rules,
            bindings=fixture.bindings,
            executor_factory=executor_factory,
        )
        preparations = worker.prepare()
        result = worker.poll_once()
        payload = _success_payload(
            fixture=fixture,
            preparations=preparations,
            result=result,
            recorders=recorders,
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
        if profile_store is not None:
            profiles_disabled = _disable_profiles(
                profile_store,
                saved_profile_keys,
            )
            profile_store.close()
        if audit_store is not None:
            audit_store.close()
        if holdings_store is not None:
            holdings_store.close()
        if engine is not None:
            engine.dispose()

    if failure is not None or payload is None:
        _print_json(
            {
                "ok": False,
                "mode": "staging_mstr_btc_shadow",
                "error": failure or "smoke did not produce a result",
                "profiles_disabled": profiles_disabled,
                "order_submitted": False,
            },
            stream=sys.stderr,
        )
        return 5

    payload["profiles_disabled"] = profiles_disabled
    payload["ok"] = bool(payload["ok"] and profiles_disabled)
    _print_json(
        payload,
        stream=sys.stdout if payload["ok"] else sys.stderr,
    )
    return 0 if payload["ok"] else 5


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Persist one staging-only parser-bypassed MSTR fact and run "
            "three synthetic market profiles through the hosted worker "
            "and DryRunPreparedExecutor."
        )
    )
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"Required literal confirmation: {_CONFIRMATION}.",
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
        return "explicit STAGING_MSTR_SHADOW confirmation is required"
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
    if args.run_id and not _RUN_ID_PATTERN.fullmatch(args.run_id):
        return "run id must contain 3-48 safe characters"
    return None


def _build_fixture(
    *,
    run_id: str,
    now: datetime,
    baseline: MstrBtcHoldingsBaseline,
) -> _SmokeFixture:
    weekly_scope_id = f"{_SMOKE_PREFIX}{run_id}"
    activity_rows = (
        ("purchase-any", MstrBtcActivity.ACQUIRED, Decimal("0"), None),
        (
            "purchase-over-1000",
            MstrBtcActivity.ACQUIRED,
            Decimal("1000"),
            1,
        ),
        ("sale-any", MstrBtcActivity.SOLD, Decimal("0"), None),
    )
    rules: list[MstrBtcResolutionRule] = []
    bindings: list[MstrBtcMarketBinding] = []
    profiles: list[ResolutionExecutionProfile] = []
    for suffix, activity, threshold, tolerance in activity_rows:
        rule_key = f"{weekly_scope_id}-{suffix}"
        signal_id = f"{weekly_scope_id}:{suffix}"
        condition_id = "0x" + hashlib.sha256(
            f"condition:{run_id}:{suffix}".encode("utf-8")
        ).hexdigest()
        binding = MstrBtcMarketBinding(
            rule_key=rule_key,
            signal_id=signal_id,
            market_slug=f"{weekly_scope_id}-{suffix}",
            condition_id=condition_id,
        )
        rule = MstrBtcResolutionRule(
            rule_key=rule_key,
            signal_id=signal_id,
            weekly_scope_id=weekly_scope_id,
            activity=activity,
            comparison_op=">",
            threshold_btc=threshold,
            explicit_boundary_tolerance_btc=tolerance,
        )
        profile = ResolutionExecutionProfile(
            profile_key=f"{weekly_scope_id}-{suffix}",
            scope_id=signal_id,
            source_name=MSTR_BTC_SOURCE_NAME,
            source_reference=binding.source_reference,
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
                "staging_mstr_smoke": True,
                "ticker": "MSTR",
                "weekly_scope_id": weekly_scope_id,
            },
        )
        rules.append(rule)
        bindings.append(binding)
        profiles.append(profile)

    provider_event_id = f"{weekly_scope_id}-filing"
    source_url = (
        f"https://synthetic.invalid/codexpoly/mstr-btc/{run_id}"
    )
    fingerprint = hashlib.sha256(
        f"document:{run_id}".encode("utf-8")
    ).hexdigest()
    event = MstrBtcDocumentCandidate(
        scope_id=weekly_scope_id,
        provider=MstrBtcProvider.SEC,
        provider_event_id=provider_event_id,
        ticker="MSTR",
        cik="1050446",
        form_type="8-K",
        source_url=source_url,
        filing_url=f"{source_url}/filing",
        filed_at=now,
        received_at=now,
        transport_fingerprint=fingerprint,
        metadata={
            "parser_bypassed": True,
            "staging_mstr_smoke": True,
        },
    )
    fact = MstrBtcFactCandidate(
        scope_id=weekly_scope_id,
        provider=MstrBtcProvider.SEC,
        provider_event_id=provider_event_id,
        baseline_state_id=baseline.state_id,
        holdings_before_btc=baseline.holdings_btc,
        holdings_after_btc=baseline.holdings_btc + 1_500,
        net_change_btc=1_500,
        acquired_btc=1_500,
        sold_btc=None,
        acquired_derivation=MstrBtcValueDerivation.EXPLICIT,
        sold_derivation=MstrBtcValueDerivation.NOT_CONFIRMED,
        holdings_crosscheck_difference_btc=0,
        source_url=source_url,
        filing_url=f"{source_url}/filing",
        published_at=now,
        detected_at=now,
        parser_name="staging_synthetic_parser_bypass",
        parser_version="1",
        document_fingerprint=fingerprint,
        evidence_excerpts=(
            "Synthetic holdings-first fact; parser bypassed.",
        ),
        attributes={
            "parser_bypassed": True,
            "staging_mstr_smoke": True,
            "ticker": "MSTR",
            "cik": "1050446",
        },
    )
    return _SmokeFixture(
        run_id=run_id,
        weekly_scope_id=weekly_scope_id,
        rules=tuple(rules),
        bindings=tuple(bindings),
        event=event,
        fact=fact,
        profiles=tuple(profiles),
    )


def _persist_fixture(
    fixture: _SmokeFixture,
    *,
    audit_store: SqlAlchemyMstrBtcAuditStore,
    profile_store: SqlAlchemyResolutionProfileStore,
    saved_profile_keys: list[str],
) -> None:
    source_record = audit_store.record_source_event(fixture.event)
    fact_record = audit_store.record_fact(
        source_event_id=source_record.row_id,
        candidate=fixture.fact,
        reason="staging_synthetic_parser_bypass",
    )
    audit_store.record_processing_result(
        source_event_id=source_record.row_id,
        status=MstrBtcAuditStatus.ACCEPTED,
        reason="staging_synthetic_parser_bypass",
        baseline_state_id=fixture.fact.baseline_state_id,
        fact_candidate_id=fact_record.row_id,
    )
    for profile in fixture.profiles:
        profile_store.save(profile)
        saved_profile_keys.append(profile.profile_key)
        profile_store.set_enabled(
            profile.profile_key,
            enabled=True,
        )


def _retire_stale_profiles(engine: Any) -> None:
    from sqlalchemy import text

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE resolution_execution_profiles
                SET status = 'DISABLED', updated_at = now()
                WHERE profile_key LIKE :prefix
                  AND status <> 'DISABLED'
                """
            ),
            {"prefix": f"{_SMOKE_PREFIX}%"},
        )


def _disable_profiles(
    profile_store: SqlAlchemyResolutionProfileStore,
    profile_keys: Sequence[str],
) -> bool:
    success = True
    for profile_key in profile_keys:
        try:
            profile_store.set_enabled(profile_key, enabled=False)
        except Exception:
            success = False
    return success


def _success_payload(
    *,
    fixture: _SmokeFixture,
    preparations: Sequence[Any],
    result: Any,
    recorders: Mapping[str, _RecordingDryRunExecutor],
) -> dict[str, Any]:
    rows = []
    expected = {
        "purchase-any": "YES",
        "purchase-over-1000": "YES",
        "sale-any": "NO",
    }
    for profile in fixture.profiles:
        recorder = recorders.get(profile.profile_key)
        suffix = profile.profile_key.rsplit("-", 2)[-1]
        if profile.profile_key.endswith("purchase-over-1000"):
            suffix = "purchase-over-1000"
        elif profile.profile_key.endswith("purchase-any"):
            suffix = "purchase-any"
        elif profile.profile_key.endswith("sale-any"):
            suffix = "sale-any"
        intents = recorder.intents if recorder is not None else ()
        results = recorder.results if recorder is not None else ()
        rows.append(
            {
                "profile_key": profile.profile_key,
                "prepared_template_count": (
                    len(recorder.prepared_template_ids)
                    if recorder is not None
                    else 0
                ),
                "selected_outcome": (
                    intents[0].outcome.value
                    if len(intents) == 1
                    else None
                ),
                "expected_outcome": expected[suffix],
                "execution_status": (
                    results[0].status.value
                    if len(results) == 1
                    else None
                ),
                "execution_attempted": (
                    bool(results[0].attempted)
                    if len(results) == 1
                    else None
                ),
            }
        )
    ok = (
        len(preparations) == 3
        and all(row.ready for row in preparations)
        and all(row.template_count == 2 for row in preparations)
        and result.fact_count == 1
        and result.completed_count == 3
        and result.failed_count == 0
        and all(
            row["prepared_template_count"] == 2
            and row["selected_outcome"] == row["expected_outcome"]
            and row["execution_status"] == "DRY_RUN"
            and row["execution_attempted"] is False
            for row in rows
        )
    )
    return {
        "ok": ok,
        "mode": "staging_mstr_btc_shadow",
        "run_id": fixture.run_id,
        "parser_bypassed": True,
        "append_only_fixture_retained": True,
        "path": [
            "mstr_btc_fact_candidates",
            "MstrBtcResolutionSource",
            "ResolutionSignal",
            "NumericThresholdStrategy",
            "OrderIntent",
            "DryRunPreparedExecutor",
        ],
        "prepared_profile_count": len(preparations),
        "completed_count": result.completed_count,
        "failed_count": result.failed_count,
        "markets": rows,
        "order_submitted": any(
            result_row.attempted
            for recorder in recorders.values()
            for result_row in recorder.results
        ),
    }


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _is_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _print_json(payload: object, *, stream: object) -> None:
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
