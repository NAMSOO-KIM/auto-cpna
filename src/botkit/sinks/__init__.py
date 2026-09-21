"""발송 싱크 레지스트리. 잡 YAML의 sinks[].type으로 구현을 고른다."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from botkit.jobspec import JobSpec, TelegramSink, WebhookSink
from botkit.llm import render
from botkit.sinks import telegram, webhook


def build_header(job: JobSpec, sink: TelegramSink, now: dt.datetime) -> str:
    """텔레그램 머리말의 {date}/{time}/{job_title} 치환. 프롬프트와 같은 규칙을 쓴다."""
    if not sink.header:
        return ""
    local_now = now.astimezone(ZoneInfo(job.schedule.timezone))
    return render(
        sink.header,
        {
            "date": local_now.strftime("%Y-%m-%d"),
            "time": local_now.strftime("%H:%M"),
            "job_title": job.title,
        },
    )


def deliver(job: JobSpec, text: str, now: dt.datetime) -> list[str]:
    """모든 싱크로 발송하고 사람이 읽을 결과 요약을 반환.

    싱크 하나가 실패하면 즉시 올린다 - 고객 채널로 보고가 안 갔다는 사실은
    조용히 삼키면 안 되고, 워크플로의 실패 알림으로 운영자에게 닿아야 한다.
    """
    results: list[str] = []
    for sink in job.sinks:
        if isinstance(sink, TelegramSink):
            ids = telegram.send(sink, text, header=build_header(job, sink, now))
            results.append(f"telegram: {len(ids)}개 메시지 발송")
        elif isinstance(sink, WebhookSink):
            status = webhook.send(sink, text)
            results.append(f"webhook({sink.url_env}): HTTP {status}")
        else:
            raise ValueError(f"지원하지 않는 싱크 타입입니다: {type(sink).__name__}")
    return results
