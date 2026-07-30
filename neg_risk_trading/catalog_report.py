from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from cbr_trading.secret_guard import redact_exception
from neg_risk_trading.catalog_repository import (
    SqlAlchemyCatalogRepository,
)
from neg_risk_trading.settings import NegRiskCatalogSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read the current public neg-risk catalog summary"
        )
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="number of READY_FOR_L2_REPLAY events to include",
    )
    args = parser.parse_args(argv)
    repository: SqlAlchemyCatalogRepository | None = None
    try:
        settings = NegRiskCatalogSettings.from_env()
        repository = SqlAlchemyCatalogRepository(
            settings.database_url
        )
        repository.ensure_ready()
        report = repository.report(top_limit=args.top)
        print(
            json.dumps(
                report,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                default=_json_default,
            )
        )
    except Exception as exc:
        print(
            "Neg-risk catalog report failed: "
            f"{redact_exception(exc)}",
            file=sys.stderr,
        )
        return 1
    finally:
        if repository is not None:
            repository.close()
    return 0


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    raise TypeError(
        f"Unsupported catalog report type: {type(value).__name__}"
    )


if __name__ == "__main__":
    sys.exit(main())
