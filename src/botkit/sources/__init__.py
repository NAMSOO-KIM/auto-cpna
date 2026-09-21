"""수집 소스 레지스트리. 잡 YAML의 source.type으로 커넥터를 고른다."""
from __future__ import annotations

from botkit.jobspec import (
    GoogleSheetSource,
    HttpJsonSource,
    RssSource,
    StaticSource,
)
from botkit.sources.google_sheet import fetch_google_sheet
from botkit.sources.http_json import fetch_http_json
from botkit.sources.rss import fetch_rss


def fetch_rows(source) -> list[dict]:
    """소스 스펙 -> 행 목록(dict 리스트). 키 이름은 그대로 프롬프트에 노출된다."""
    if isinstance(source, GoogleSheetSource):
        return fetch_google_sheet(source)
    if isinstance(source, RssSource):
        return fetch_rss(source)
    if isinstance(source, HttpJsonSource):
        return fetch_http_json(source)
    if isinstance(source, StaticSource):
        return list(source.rows)
    raise ValueError(f"지원하지 않는 소스 타입입니다: {type(source).__name__}")
