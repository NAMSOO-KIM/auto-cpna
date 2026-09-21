"""임의의 JSON 엔드포인트 수집 (고객사 어드민 / Apps Script 웹앱 연동용)."""
from __future__ import annotations

import httpx

from botkit.jobspec import HttpJsonSource
from botkit.settings import resolve_env_reference

TIMEOUT = 30.0


def dig(payload, items_path: str):
    """"data.items" 같은 점 표기로 응답 안의 목록을 찾아 들어간다."""
    current = payload
    for part in filter(None, items_path.split(".")):
        if not isinstance(current, dict) or part not in current:
            raise RuntimeError(
                f"응답에서 items_path '{items_path}'의 '{part}' 키를 찾지 못했습니다. "
                f"실제 최상위 키: {list(current) if isinstance(current, dict) else type(current).__name__}"
            )
        current = current[part]
    return current


def normalize(payload, source: HttpJsonSource) -> list[dict]:
    items = dig(payload, source.items_path)
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise RuntimeError(f"items_path가 가리키는 값이 목록이 아닙니다: {type(items).__name__}")

    rows = []
    for item in items[: source.limit]:
        row = item if isinstance(item, dict) else {"value": item}
        if source.fields:
            row = {key: row.get(key, "") for key in source.fields}
        rows.append(row)
    return rows


def fetch_http_json(source: HttpJsonSource) -> list[dict]:
    headers = {k: resolve_env_reference(v) for k, v in source.headers.items()}
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        response = client.request(
            source.method, source.url, headers=headers, json=source.json_body
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"응답이 JSON이 아닙니다: {response.text[:200]}") from exc
    return normalize(payload, source)
