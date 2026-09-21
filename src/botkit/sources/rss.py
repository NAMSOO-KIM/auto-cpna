"""RSS 2.0 / Atom 피드 수집.

키워드 모니터링 잡은 대부분 이 커넥터 하나로 끝난다 - 네이버 뉴스 검색 RSS,
구글 뉴스 검색 RSS, 경쟁사 블로그 피드가 모두 같은 포맷이다. feedparser 같은
추가 의존성 없이 표준 라이브러리 파서만 쓴다(납품본을 가볍게 유지).
"""
from __future__ import annotations

import datetime as dt
import html
import re
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx

from botkit.jobspec import RssSource

TIMEOUT = 30.0
ATOM_NS = "{http://www.w3.org/2005/Atom}"
TAG_RE = re.compile(r"<[^>]+>")


def strip_html(value: str, limit: int) -> str:
    text = html.unescape(TAG_RE.sub(" ", value or ""))
    text = " ".join(text.split())
    return text[:limit]


def _parse_date(value: str) -> dt.datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)  # RSS: RFC 822
    except (TypeError, ValueError):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))  # Atom
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def parse_feed(xml_text: str, summary_chars: int) -> list[dict]:
    """RSS item / Atom entry를 공통 스키마(title, link, published, summary)로."""
    root = ElementTree.fromstring(xml_text)
    entries: list[dict] = []

    for item in root.iter("item"):
        entries.append(
            {
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "published": (item.findtext("pubDate") or "").strip(),
                "summary": strip_html(item.findtext("description") or "", summary_chars),
            }
        )

    for entry in root.iter(f"{ATOM_NS}entry"):
        link = entry.find(f"{ATOM_NS}link")
        entries.append(
            {
                "title": (entry.findtext(f"{ATOM_NS}title") or "").strip(),
                "link": (link.get("href") if link is not None else "") or "",
                "published": (
                    entry.findtext(f"{ATOM_NS}published")
                    or entry.findtext(f"{ATOM_NS}updated")
                    or ""
                ).strip(),
                "summary": strip_html(
                    entry.findtext(f"{ATOM_NS}summary")
                    or entry.findtext(f"{ATOM_NS}content")
                    or "",
                    summary_chars,
                ),
            }
        )

    return entries


def filter_recent(
    entries: list[dict], since_hours: int | None, now: dt.datetime | None = None
) -> list[dict]:
    """since_hours 이내 항목만. 날짜를 못 읽은 항목은 남긴다.

    발행 시각 포맷이 제각각인 피드에서 날짜 파싱 실패로 기사를 버리면, 고객은
    '아침 보고에 그 기사가 왜 없냐'고 묻는다. 누락보다 중복이 낫다.
    """
    if since_hours is None:
        return entries
    cutoff = (now or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(hours=since_hours)
    kept = []
    for entry in entries:
        parsed = _parse_date(entry.get("published", ""))
        if parsed is None or parsed >= cutoff:
            kept.append(entry)
    return kept


def _sort_key(entry: dict) -> dt.datetime:
    parsed = _parse_date(entry.get("published", ""))
    return parsed or dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def fetch_rss(source: RssSource) -> list[dict]:
    entries: list[dict] = []
    failures: list[str] = []
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        for feed_url in source.feeds:
            try:
                response = client.get(feed_url)
                response.raise_for_status()
                entries.extend(parse_feed(response.text, source.summary_chars))
            except (httpx.HTTPError, ElementTree.ParseError) as exc:
                # 피드 하나가 죽어도 나머지로 보고는 나가야 한다. 전부 실패한
                # 경우에만 에러로 올린다.
                failures.append(f"{feed_url}: {exc}")

    if failures and not entries:
        raise RuntimeError("피드를 하나도 읽지 못했습니다:\n" + "\n".join(failures))

    recent = filter_recent(entries, source.since_hours)
    # 같은 기사가 여러 피드에 걸쳐 들어오는 경우가 흔해 링크 기준으로 중복 제거.
    seen: set[str] = set()
    unique = []
    for entry in sorted(recent, key=_sort_key, reverse=True):
        key = entry.get("link") or entry.get("title", "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique[: source.limit]
