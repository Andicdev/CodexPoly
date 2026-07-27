from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)
from xml.etree import ElementTree

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsMarketRule,
    EarningsProvider,
    SourceAuthority,
)


_PUBLIC_PROVIDERS = frozenset(
    {
        EarningsProvider.COMPANY_IR,
        EarningsProvider.PRESS_RELEASE_RSS,
        EarningsProvider.GLOBE_NEWSWIRE,
        EarningsProvider.BUSINESS_WIRE,
        EarningsProvider.PR_NEWSWIRE,
    }
)
_FEED_CONTENT_TYPES = frozenset(
    {
        "application/atom+xml",
        "application/rss+xml",
        "application/xml",
        "text/xml",
    }
)
_WORDPRESS_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "text/json",
    }
)
_HTML_LISTING_CONTENT_TYPES = frozenset(
    {
        "application/xhtml+xml",
        "text/html",
    }
)
_DOCUMENT_CONTENT_TYPES = frozenset(
    {
        "application/xhtml+xml",
        "application/xml",
        "text/html",
        "text/plain",
    }
)
_XML_FORBIDDEN_MARKERS = (b"<!doctype", b"<!entity")
_PUBLIC_LISTING_KINDS = frozenset(
    {"html_listing", "rss", "wordpress_rest"}
)


class PublicReleaseSourceError(RuntimeError):
    """Sanitized public IR or press-wire transport failure."""


@dataclass(frozen=True)
class PublicReleaseWatch:
    """Checked configuration for one official public release feed."""

    scope_id: str
    ticker: str
    cik: str
    provider: EarningsProvider
    kind: str
    feed_url: str
    allowed_document_hosts: tuple[str, ...]
    title_all: tuple[str, ...]
    title_none: tuple[str, ...] = ()
    listing_utc_offset_minutes: int = 0

    def __post_init__(self) -> None:
        for name in ("scope_id", "ticker", "cik"):
            normalized = str(getattr(self, name) or "").strip()
            if not normalized:
                raise ValueError(f"{name} is required")
            object.__setattr__(
                self,
                name,
                normalized.upper() if name == "ticker" else normalized,
            )
        if self.provider not in _PUBLIC_PROVIDERS:
            raise ValueError("provider is not a public release provider")
        kind = str(self.kind or "").strip().casefold()
        if kind not in _PUBLIC_LISTING_KINDS:
            raise ValueError("unsupported public release source kind")
        object.__setattr__(self, "kind", kind)
        _require_public_url(
            self.feed_url,
            allowed_hosts=(_url_host(self.feed_url),),
            label="feed URL",
        )
        allowed_hosts = tuple(
            sorted(
                {
                    _normalized_host(host)
                    for host in self.allowed_document_hosts
                }
            )
        )
        if not allowed_hosts:
            raise ValueError(
                "allowed_document_hosts must not be empty"
            )
        object.__setattr__(
            self,
            "allowed_document_hosts",
            allowed_hosts,
        )
        title_all = _normalized_terms(self.title_all)
        if not title_all:
            raise ValueError("title_all must not be empty")
        object.__setattr__(self, "title_all", title_all)
        object.__setattr__(
            self,
            "title_none",
            _normalized_terms(self.title_none),
        )
        listing_utc_offset_minutes = int(
            self.listing_utc_offset_minutes
        )
        if not -720 <= listing_utc_offset_minutes <= 840:
            raise ValueError(
                "listing_utc_offset_minutes is invalid"
            )
        object.__setattr__(
            self,
            "listing_utc_offset_minutes",
            listing_utc_offset_minutes,
        )


@dataclass(frozen=True)
class PublicReleasePollResult:
    candidates: tuple[EarningsDocumentCandidate, ...]
    feed_count: int
    success_count: int
    not_modified_count: int
    error_count: int


@dataclass(frozen=True)
class _FeedItem:
    event_id: str
    title: str
    link: str
    published_at: datetime
    contributor: str | None


def public_release_watches_from_rules(
    rules: Sequence[EarningsMarketRule],
) -> tuple[PublicReleaseWatch, ...]:
    """Build HTTP watches from checked, database-backed rule policies."""

    watches: list[PublicReleaseWatch] = []
    for rule in rules:
        for policy_name, default_provider in (
            ("company_ir", EarningsProvider.COMPANY_IR),
            ("press_wire", EarningsProvider.PRESS_RELEASE_RSS),
        ):
            raw_policy = rule.source_policy.get(policy_name)
            if not raw_policy:
                continue
            if not isinstance(raw_policy, Mapping):
                raise ValueError(
                    f"{policy_name} source policy must be an object"
                )
            kind = str(raw_policy.get("kind") or "").strip().casefold()
            if kind not in _PUBLIC_LISTING_KINDS:
                raise ValueError(
                    f"{policy_name} source kind is unsupported"
                )
            provider_value = str(
                raw_policy.get("provider")
                or default_provider.value
            ).strip().casefold()
            try:
                provider = EarningsProvider(provider_value)
            except ValueError:
                raise ValueError(
                    f"{policy_name} provider is unsupported"
                ) from None
            watches.append(
                PublicReleaseWatch(
                    scope_id=rule.scope_id,
                    ticker=rule.ticker,
                    cik=rule.cik,
                    provider=provider,
                    kind=kind,
                    feed_url=str(
                        raw_policy.get("feed_url") or ""
                    ).strip(),
                    allowed_document_hosts=_string_tuple(
                        raw_policy.get("allowed_document_hosts")
                    ),
                    title_all=_string_tuple(
                        raw_policy.get("title_all")
                    ),
                    title_none=_string_tuple(
                        raw_policy.get("title_none")
                    ),
                    listing_utc_offset_minutes=int(
                        raw_policy.get(
                            "listing_utc_offset_minutes",
                            0,
                        )
                    ),
                )
            )
    return tuple(watches)


class PublicReleaseFeedClient:
    """Poll bounded RSS/Atom feeds and route exact official releases."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float,
        max_bytes: int = 2 * 1024 * 1024,
        opener: Callable[..., Any] | None = None,
        logger: logging.Logger | None = None,
    ):
        normalized_agent = str(user_agent or "").strip()
        if not normalized_agent:
            raise ValueError("user_agent is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not 1024 <= int(max_bytes) <= 8 * 1024 * 1024:
            raise ValueError(
                "max_bytes must be between 1024 and 8388608"
            )
        self._user_agent = normalized_agent
        self._timeout = float(timeout)
        self._max_bytes = int(max_bytes)
        self._opener = opener
        self._logger = logger or logging.getLogger(
            "cbr_trading.earnings.public"
        )
        self._validators: dict[str, tuple[str | None, str | None]] = {}

    def poll(
        self,
        watches: Sequence[PublicReleaseWatch],
        *,
        received_at: datetime | None = None,
    ) -> PublicReleasePollResult:
        watch_rows = tuple(watches)
        if any(
            not isinstance(watch, PublicReleaseWatch)
            for watch in watch_rows
        ):
            raise TypeError(
                "watches must contain PublicReleaseWatch objects"
            )
        detected_at = _as_utc(
            received_at or datetime.now(timezone.utc),
            "received_at",
        )
        by_feed: dict[
            tuple[str, str, int],
            list[PublicReleaseWatch],
        ] = defaultdict(list)
        for watch in watch_rows:
            by_feed[
                (
                    watch.kind,
                    watch.feed_url,
                    watch.listing_utc_offset_minutes,
                )
            ].append(watch)

        candidates: list[EarningsDocumentCandidate] = []
        successes = 0
        not_modified = 0
        errors = 0
        for (
            kind,
            feed_url,
            listing_utc_offset_minutes,
        ), feed_watches in sorted(by_feed.items()):
            try:
                document = self._fetch_listing(
                    feed_url,
                    kind=kind,
                )
                if document is None:
                    not_modified += 1
                    continue
                items = _parse_listing(
                    document,
                    kind=kind,
                    listing_utc_offset_minutes=(
                        listing_utc_offset_minutes
                    ),
                )
                successes += 1
                for watch in feed_watches:
                    for item in items:
                        if not _title_matches(item.title, watch):
                            continue
                        try:
                            candidates.append(
                                _candidate_from_item(
                                    item,
                                    watch=watch,
                                    received_at=detected_at,
                                )
                            )
                        except PublicReleaseSourceError:
                            errors += 1
                            self._logger.warning(
                                "Public release item rejected "
                                "provider=%s scope=%s "
                                "error_code=invalid_item_url",
                                watch.provider.value,
                                watch.scope_id,
                            )
            except Exception as exc:
                errors += 1
                self._logger.warning(
                    "Public release feed poll failed host=%s "
                    "error_code=%s",
                    _url_host(feed_url),
                    type(exc).__name__,
                )
        return PublicReleasePollResult(
            candidates=tuple(candidates),
            feed_count=len(by_feed),
            success_count=successes,
            not_modified_count=not_modified,
            error_count=errors,
        )

    def _fetch_listing(
        self,
        feed_url: str,
        *,
        kind: str,
    ) -> bytes | None:
        feed_host = _url_host(feed_url)
        _require_public_url(
            feed_url,
            allowed_hosts=(feed_host,),
            label="feed URL",
        )
        etag, modified = self._validators.get(
            feed_url,
            (None, None),
        )
        if kind == "rss":
            accept = (
                "application/rss+xml,application/atom+xml,"
                "application/xml,text/xml;q=0.9,*/*;q=0.1"
            )
            accepted_content_types = _FEED_CONTENT_TYPES
        elif kind == "html_listing":
            accept = (
                "text/html,application/xhtml+xml;q=0.9,"
                "*/*;q=0.1"
            )
            accepted_content_types = _HTML_LISTING_CONTENT_TYPES
        elif kind == "wordpress_rest":
            accept = "application/json,text/json;q=0.9,*/*;q=0.1"
            accepted_content_types = _WORDPRESS_CONTENT_TYPES
        else:
            raise PublicReleaseSourceError(
                "unsupported public release source kind"
            )
        headers = {
            "User-Agent": self._user_agent,
            "Accept": accept,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        request = Request(
            feed_url,
            headers=headers,
            method="GET",
        )
        opener = self._opener or _allowlisted_opener((feed_host,))
        try:
            response_context = opener(
                request,
                timeout=self._timeout,
            )
        except HTTPError as exc:
            if exc.code == 304:
                return None
            raise PublicReleaseSourceError(
                "public release feed request failed"
            ) from None
        with response_context as response:
            status = int(getattr(response, "status", 200))
            if status == 304:
                return None
            if status != 200:
                raise PublicReleaseSourceError(
                    "public release feed returned a non-success status"
                )
            final_url = str(
                response.geturl()
                if hasattr(response, "geturl")
                else feed_url
            )
            _require_public_url(
                final_url,
                allowed_hosts=(feed_host,),
                label="feed redirect",
            )
            content_type = _content_type(response)
            if (
                content_type
                and content_type not in accepted_content_types
            ):
                raise PublicReleaseSourceError(
                    "public release listing has unsupported content type"
                )
            document = response.read(self._max_bytes + 1)
            response_headers = getattr(response, "headers", None)
            next_etag = _header(response_headers, "ETag")
            next_modified = _header(
                response_headers,
                "Last-Modified",
            )
        if not document:
            raise PublicReleaseSourceError(
                "public release listing is empty"
            )
        if len(document) > self._max_bytes:
            raise PublicReleaseSourceError(
                "public release listing exceeds the size limit"
            )
        self._validators[feed_url] = (
            next_etag or etag,
            next_modified or modified,
        )
        return document

    def close(self) -> None:
        return None


class PublicReleaseDocumentFetcher:
    """Fetch only the allowlisted public document selected by a watch."""

    def __init__(
        self,
        *,
        watches: Sequence[PublicReleaseWatch],
        user_agent: str,
        timeout: float,
        max_bytes: int,
        opener: Callable[..., Any] | None = None,
    ):
        normalized_agent = str(user_agent or "").strip()
        if not normalized_agent:
            raise ValueError("user_agent is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_bytes < 1024:
            raise ValueError("max_bytes must be at least 1024")
        allowed: dict[tuple[str, EarningsProvider], set[str]] = defaultdict(set)
        for watch in watches:
            allowed[(watch.scope_id, watch.provider)].update(
                watch.allowed_document_hosts
            )
        self._allowed_hosts = {
            key: tuple(sorted(hosts))
            for key, hosts in allowed.items()
        }
        self._user_agent = normalized_agent
        self._timeout = float(timeout)
        self._max_bytes = int(max_bytes)
        self._opener = opener

    def fetch(
        self,
        candidate: EarningsDocumentCandidate,
    ) -> bytes:
        key = (candidate.scope_id, candidate.provider)
        allowed_hosts = self._allowed_hosts.get(key)
        if not allowed_hosts:
            raise PublicReleaseSourceError(
                "public release candidate has no configured watch"
            )
        _require_public_url(
            candidate.source_url,
            allowed_hosts=allowed_hosts,
            label="release URL",
        )
        request = Request(
            candidate.source_url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "text/plain;q=0.9,*/*;q=0.1"
                ),
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
            method="GET",
        )
        opener = self._opener or _allowlisted_opener(allowed_hosts)
        with opener(request, timeout=self._timeout) as response:
            status = int(getattr(response, "status", 200))
            if status != 200:
                raise PublicReleaseSourceError(
                    "public release returned a non-success status"
                )
            final_url = str(
                response.geturl()
                if hasattr(response, "geturl")
                else candidate.source_url
            )
            _require_public_url(
                final_url,
                allowed_hosts=allowed_hosts,
                label="release redirect",
            )
            content_type = _content_type(response)
            if (
                content_type
                and content_type not in _DOCUMENT_CONTENT_TYPES
            ):
                raise PublicReleaseSourceError(
                    "public release has unsupported content type"
                )
            document = response.read(self._max_bytes + 1)
        if not document:
            raise PublicReleaseSourceError(
                "public release document is empty"
            )
        if len(document) > self._max_bytes:
            raise PublicReleaseSourceError(
                "public release document exceeds the size limit"
            )
        return document


def _candidate_from_item(
    item: _FeedItem,
    *,
    watch: PublicReleaseWatch,
    received_at: datetime,
) -> EarningsDocumentCandidate:
    _require_public_url(
        item.link,
        allowed_hosts=watch.allowed_document_hosts,
        label="release URL",
    )
    fingerprint = hashlib.sha256(
        (
            f"{watch.provider.value}|{item.event_id}|"
            f"{item.link}|{item.published_at.isoformat()}"
        ).encode("utf-8")
    ).hexdigest()
    return EarningsDocumentCandidate(
        scope_id=watch.scope_id,
        provider=watch.provider,
        provider_event_id=item.event_id,
        ticker=watch.ticker,
        cik=watch.cik,
        form_type="PRESS_RELEASE",
        items=(),
        document_type="HTML",
        source_url=item.link,
        filing_url=item.link,
        filed_at=item.published_at,
        received_at=received_at,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint=fingerprint,
        metadata={
            "feed_url": watch.feed_url,
            "listing_kind": watch.kind,
            "release_title": item.title,
            "contributor": item.contributor,
        },
    )


def _parse_feed(document: bytes) -> tuple[_FeedItem, ...]:
    lowered = document[:64 * 1024].lower()
    if any(marker in lowered for marker in _XML_FORBIDDEN_MARKERS):
        raise PublicReleaseSourceError(
            "public release feed contains forbidden XML declarations"
        )
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError:
        raise PublicReleaseSourceError(
            "public release feed is invalid XML"
        ) from None
    items: list[_FeedItem] = []
    for element in root.iter():
        if _local_name(element.tag) not in {"item", "entry"}:
            continue
        title = _child_text(element, "title")
        link = _entry_link(element)
        published = (
            _child_text(element, "pubDate")
            or _child_text(element, "published")
            or _child_text(element, "updated")
        )
        event_id = (
            _child_text(element, "identifier")
            or _child_text(element, "guid")
            or _child_text(element, "id")
            or link
        )
        if not title or not link or not published or not event_id:
            continue
        try:
            published_at = _parse_datetime(published)
        except (TypeError, ValueError):
            continue
        items.append(
            _FeedItem(
                event_id=event_id,
                title=title,
                link=link,
                published_at=published_at,
                contributor=_child_text(element, "contributor"),
            )
        )
    return tuple(items)


def _parse_listing(
    document: bytes,
    *,
    kind: str,
    listing_utc_offset_minutes: int,
) -> tuple[_FeedItem, ...]:
    if kind == "rss":
        return _parse_feed(document)
    if kind == "html_listing":
        return _parse_html_listing(
            document,
            listing_utc_offset_minutes=(
                listing_utc_offset_minutes
            ),
        )
    if kind == "wordpress_rest":
        return _parse_wordpress_rest(document)
    raise PublicReleaseSourceError(
        "unsupported public release source kind"
    )


def _parse_html_listing(
    document: bytes,
    *,
    listing_utc_offset_minutes: int,
) -> tuple[_FeedItem, ...]:
    try:
        decoded = document.decode("utf-8")
    except UnicodeDecodeError:
        try:
            decoded = document.decode("windows-1252")
        except UnicodeDecodeError:
            raise PublicReleaseSourceError(
                "public release HTML listing has invalid encoding"
            ) from None
    parser = _ReleaseListingHtmlParser()
    try:
        parser.feed(decoded)
        parser.close()
    except Exception:
        raise PublicReleaseSourceError(
            "public release HTML listing is invalid"
        ) from None
    items: list[_FeedItem] = []
    for event_id, title, link, published in parser.rows:
        try:
            published_at = _parse_html_listing_datetime(
                published,
                listing_utc_offset_minutes=(
                    listing_utc_offset_minutes
                ),
            )
        except (TypeError, ValueError):
            continue
        items.append(
            _FeedItem(
                event_id=event_id,
                title=title,
                link=link,
                published_at=published_at,
                contributor=None,
            )
        )
    return tuple(items)


class _ReleaseListingHtmlParser(HTMLParser):
    """Extract bounded ``div.release`` records from an IR listing."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str, str, str]] = []
        self._release_depth = 0
        self._in_date = False
        self._in_link = False
        self._date_parts: list[str] = []
        self._title_parts: list[str] = []
        self._title_attribute = ""
        self._link = ""

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized = tag.casefold()
        attributes = {
            str(name).casefold(): str(value or "")
            for name, value in attrs
        }
        if normalized == "div":
            classes = {
                item.casefold()
                for item in attributes.get("class", "").split()
            }
            if self._release_depth:
                self._release_depth += 1
            elif "release" in classes:
                self._release_depth = 1
                self._date_parts = []
                self._title_parts = []
                self._title_attribute = ""
                self._link = ""
            return
        if not self._release_depth:
            return
        if normalized == "p":
            classes = {
                item.casefold()
                for item in attributes.get("class", "").split()
            }
            self._in_date = "date" in classes
        elif normalized == "a":
            self._in_link = True
            self._link = attributes.get("href", "").strip()
            self._title_attribute = html.unescape(
                attributes.get("title", "")
            ).strip()

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized == "p":
            self._in_date = False
        elif normalized == "a":
            self._in_link = False
        elif normalized == "div" and self._release_depth:
            self._release_depth -= 1
            if self._release_depth == 0:
                self._finish_release()

    def handle_data(self, data: str) -> None:
        if self._in_date:
            self._date_parts.append(data)
        if self._in_link:
            self._title_parts.append(data)

    def _finish_release(self) -> None:
        published = " ".join(" ".join(self._date_parts).split())
        title = self._title_attribute or " ".join(
            " ".join(self._title_parts).split()
        )
        if published and title and self._link:
            self.rows.append(
                (self._link, title, self._link, published)
            )


def _parse_html_listing_datetime(
    value: str,
    *,
    listing_utc_offset_minutes: int,
) -> datetime:
    normalized = " ".join(str(value or "").split())
    if not normalized:
        raise ValueError("published timestamp is required")
    parsed = datetime.strptime(
        normalized,
        "%B %d, %Y %I:%M %p",
    )
    return parsed.replace(
        tzinfo=timezone(
            timedelta(minutes=listing_utc_offset_minutes)
        )
    ).astimezone(timezone.utc)


def _parse_wordpress_rest(
    document: bytes,
) -> tuple[_FeedItem, ...]:
    try:
        payload = json.loads(document)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PublicReleaseSourceError(
            "public release listing is invalid JSON"
        ) from None
    if not isinstance(payload, list):
        raise PublicReleaseSourceError(
            "public release listing must be a JSON array"
        )
    items: list[_FeedItem] = []
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        event_id = str(row.get("id") or "").strip()
        link = str(row.get("link") or "").strip()
        published = str(
            row.get("date_gmt")
            or row.get("modified_gmt")
            or ""
        ).strip()
        raw_title = row.get("title")
        if isinstance(raw_title, Mapping):
            raw_title = raw_title.get("rendered")
        title = html.unescape(str(raw_title or "")).strip()
        if not event_id or not link or not published or not title:
            continue
        try:
            published_at = _parse_wordpress_datetime(published)
        except (TypeError, ValueError):
            continue
        items.append(
            _FeedItem(
                event_id=event_id,
                title=title,
                link=link,
                published_at=published_at,
                contributor=None,
            )
        )
    return tuple(items)


def _title_matches(title: str, watch: PublicReleaseWatch) -> bool:
    normalized = _normalized_text(title)
    return (
        all(term in normalized for term in watch.title_all)
        and not any(term in normalized for term in watch.title_none)
    )


def _entry_link(element: ElementTree.Element) -> str:
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        text_value = str(child.text or "").strip()
        if text_value:
            return text_value
        href = str(child.attrib.get("href") or "").strip()
        if href:
            return href
    return ""


def _child_text(
    element: ElementTree.Element,
    local_name: str,
) -> str:
    expected = local_name.casefold()
    for child in element:
        if _local_name(child.tag).casefold() != expected:
            continue
        value = str(child.text or "").strip()
        if value:
            return value
    return ""


def _local_name(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _parse_datetime(value: str) -> datetime:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("published timestamp is required")
    try:
        parsed = parsedate_to_datetime(normalized)
    except (TypeError, ValueError):
        parsed = datetime.fromisoformat(
            normalized.replace("Z", "+00:00")
        )
    return _as_utc(parsed, "published timestamp")


def _parse_wordpress_datetime(value: str) -> datetime:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("published timestamp is required")
    parsed = datetime.fromisoformat(
        normalized.replace("Z", "+00:00")
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _normalized_terms(value: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        term
        for item in value
        if (term := _normalized_text(item))
    )


def _normalized_text(value: object) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        str(value or "").casefold(),
    ).strip()


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Sequence):
        return ()
    return tuple(
        normalized
        for item in value
        if (normalized := str(item or "").strip())
    )


def _normalized_host(value: object) -> str:
    host = str(value or "").strip().casefold().rstrip(".")
    if not host or "/" in host or ":" in host or "@" in host:
        raise ValueError("invalid allowed document host")
    return host


def _url_host(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    return str(parsed.hostname or "").casefold().rstrip(".")


def _require_public_url(
    value: str,
    *,
    allowed_hosts: Sequence[str],
    label: str,
) -> None:
    parsed = urlparse(str(value or "").strip())
    host = str(parsed.hostname or "").casefold().rstrip(".")
    normalized_allowed = {
        _normalized_host(item)
        for item in allowed_hosts
    }
    if parsed.scheme.casefold() != "https":
        raise PublicReleaseSourceError(f"{label} must use HTTPS")
    if host not in normalized_allowed:
        raise PublicReleaseSourceError(
            f"{label} left the configured domain"
        )
    if parsed.username or parsed.password:
        raise PublicReleaseSourceError(
            f"{label} cannot contain credentials"
        )
    if parsed.port not in {None, 443}:
        raise PublicReleaseSourceError(
            f"{label} cannot use a custom port"
        )
    if parsed.fragment:
        raise PublicReleaseSourceError(
            f"{label} cannot contain a fragment"
        )


class _AllowlistedRedirects(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: Sequence[str]):
        super().__init__()
        self._allowed_hosts = tuple(allowed_hosts)

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ):
        _require_public_url(
            newurl,
            allowed_hosts=self._allowed_hosts,
            label="public release redirect",
        )
        return super().redirect_request(
            req,
            fp,
            code,
            msg,
            headers,
            newurl,
        )


def _allowlisted_opener(
    allowed_hosts: Sequence[str],
) -> Callable[..., Any]:
    return build_opener(
        _AllowlistedRedirects(allowed_hosts)
    ).open


def _content_type(response: Any) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    if hasattr(headers, "get_content_type"):
        value = str(headers.get_content_type() or "").casefold()
        return value or None
    raw = _header(headers, "Content-Type")
    if not raw:
        return None
    return raw.split(";", 1)[0].strip().casefold() or None


def _header(headers: Any, name: str) -> str | None:
    if headers is None or not hasattr(headers, "get"):
        return None
    value = str(headers.get(name) or "").strip()
    return value or None
