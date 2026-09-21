"""범용 웹훅 발송. 슬랙 incoming webhook, 노션/어드민 프록시 연동에 쓴다."""
from __future__ import annotations

import httpx

from botkit.jobspec import WebhookSink
from botkit.settings import require_env, resolve_env_reference

TIMEOUT = 30.0


def send(sink: WebhookSink, text: str) -> int:
    url = require_env(sink.url_env, "웹훅 수신 URL")
    headers = {k: resolve_env_reference(v) for k, v in sink.headers.items()}
    payload = {**sink.extra_payload, sink.text_key: text}

    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(url, json=payload, headers=headers)
    if response.status_code >= 400:
        raise RuntimeError(
            f"웹훅 발송 실패 (status={response.status_code}): {response.text[:300]}"
        )
    return response.status_code
