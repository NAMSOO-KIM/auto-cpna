"""발송 싱크 레지스트리. 잡 YAML의 sinks[].type으로 구현을 고른다."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from botkit.jobspec import JobSpec, TelegramSink, WebhookSink
from botkit.llm import render
from botkit.secrets import bind_job_secrets
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


@dataclass
class DeliveryResult:
    summaries: list[str] = field(default_factory=list)
    message_ids: list[int] = field(default_factory=list)


class DeliveryError(RuntimeError):
    def __init__(self, result: DeliveryResult):
        super().__init__("발송 실패. 일부 메시지는 도착했을 수 있으니 이력과 채널을 확인하세요.")
        self.result = result


def deliver(job: JobSpec, text: str, now: dt.datetime) -> DeliveryResult:
    """모든 싱크로 발송하고 사람이 읽을 결과 요약을 반환.

    싱크 하나가 실패하면 즉시 올린다 - 고객 채널로 보고가 안 갔다는 사실은
    조용히 삼키면 안 되고, 워크플로의 실패 알림으로 운영자에게 닿아야 한다.
    """
    job = bind_job_secrets(job)
    results = DeliveryResult()
    for sink in job.sinks:
        try:
            if isinstance(sink, TelegramSink):
                ids = telegram.send(sink, text, header=build_header(job, sink, now))
                results.message_ids.extend(ids)
                results.summaries.append(f"telegram: {len(ids)}개 메시지 발송")
            elif isinstance(sink, WebhookSink):
                status = webhook.send(sink, text)
                results.summaries.append(f"webhook({sink.url_env}): HTTP {status}")
            else:
                raise ValueError(f"지원하지 않는 싱크 타입입니다: {type(sink).__name__}")
        except Exception as exc:  # noqa: BLE001 - 부분 발송 증거를 호출자에게 전달
            if isinstance(exc, telegram.TelegramSendError):
                results.message_ids.extend(exc.message_ids)
            raise DeliveryError(results) from exc
    return results
