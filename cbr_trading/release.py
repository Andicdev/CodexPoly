from __future__ import annotations

import html
import re
from datetime import datetime, timezone


DEFAULT_RELEASE_TIME_SUFFIX = "133000key_e"


def parse_datetime(value: str | None) -> datetime | None:
    """Parse supported release date formats and normalize them to UTC."""
    if not value:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d.%m.%Y",
        "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue

    return None


def build_predicted_release_url(
    *,
    now: datetime | None = None,
    release_date: str | None = None,
    release_time_suffix: str = DEFAULT_RELEASE_TIME_SUFFIX,
) -> str:
    """Build the target CBR English press-release URL used by the old worker."""
    target = now or datetime.now(timezone.utc)
    override = parse_datetime(release_date)
    if override is not None:
        target = override

    suffix = str(release_time_suffix or DEFAULT_RELEASE_TIME_SUFFIX).strip()
    return (
        "https://www.cbr.ru/eng/press/pr/?file="
        f"{target.strftime('%d%m%Y')}_{suffix}.htm"
    )


def extract_title(document_html: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", document_html or "")
    if not match:
        return ""
    without_tags = re.sub(r"(?is)<[^>]+>", " ", match.group(1))
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _compact_text(value: str) -> str:
    return " ".join((value or "").split())


def parse_release_rate_from_title(title: str) -> float | None:
    compact = _compact_text(title)
    patterns = (
        r"\bkey rate\b[^.]{0,120}?\bto\s+(\d+(?:\.\d+)?)%\s*(?:p\.a\.|per annum)?",
        r"\bkey rate\b[^.]{0,120}?\bat\s+(\d+(?:\.\d+)?)%\s*(?:p\.a\.|per annum)?",
        r"\bkeeps the key rate at\s+(\d+(?:\.\d+)?)%",
        r"\bcuts the key rate by\s+\d+\s*bp\s+to\s+(\d+(?:\.\d+)?)%",
        r"\bcuts the key rate to\s+(\d+(?:\.\d+)?)%",
        r"\braises the key rate by\s+\d+\s*bp\s+to\s+(\d+(?:\.\d+)?)%",
        r"\braises the key rate to\s+(\d+(?:\.\d+)?)%",
        r"\bincreases the key rate to\s+(\d+(?:\.\d+)?)%",
        r"\blowers the key rate to\s+(\d+(?:\.\d+)?)%",
    )
    return _first_rate_match(compact, patterns)


def _first_rate_match(value: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, value, re.IGNORECASE)
        if not match:
            continue
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            continue
    return None


def looks_like_key_rate_release(text: str) -> bool:
    compact = _compact_text(text)
    patterns = (
        r"\bkey rate\b",
        r"\bboard of directors\b[^.]{0,120}\bkey rate\b",
        r"\bdecided to\b[^.]{0,120}\bkey rate\b",
    )
    return any(re.search(pattern, compact, re.IGNORECASE) for pattern in patterns)


def classify_change(
    previous_rate: float | None,
    new_rate: float | None,
) -> tuple[float | None, str | None]:
    if previous_rate is None or new_rate is None:
        return None, None

    change_bps = round((float(new_rate) - float(previous_rate)) * 100.0, 6)
    if change_bps < 0:
        return change_bps, "decrease"
    if change_bps > 0:
        return change_bps, "increase"
    return change_bps, "no_change"
