"""수집 결과를 Claude에 넘겨 고객이 읽을 보고서 본문을 만든다."""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

import anthropic

from botkit.jobspec import JobSpec
from botkit.settings import require_env

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def render(template: str, values: dict[str, str]) -> str:
    """{key} 자리를 채운다. str.format을 쓰지 않는 이유가 있다.

    고객 맞춤 프롬프트에는 JSON 예시나 중괄호가 섞여 들어오기 마련이고,
    str.format은 그걸 만나면 KeyError/IndexError로 새벽 스케줄을 통째로
    죽인다. 여기서는 아는 키만 치환하고 나머지 중괄호는 그대로 남긴다.
    """
    return PLACEHOLDER_RE.sub(
        lambda m: values.get(m.group(1), m.group(0)),
        template,
    )


def rows_to_text(rows: list[dict], max_chars: int) -> str:
    """행 목록을 프롬프트에 넣을 텍스트로. 상한을 넘으면 뒤를 자르고 알린다.

    조용히 자르지 않는다 - 잘렸다는 사실이 프롬프트 안에 남아야 모델이
    "일부만 봤다"는 전제로 요약하고, 운영자도 로그에서 원인을 찾을 수 있다.
    """
    blocks = []
    used = 0
    for index, row in enumerate(rows, start=1):
        lines = [f"[{index}]"]
        lines += [f"{key}: {value}" for key, value in row.items() if str(value).strip()]
        block = "\n".join(lines)
        if used + len(block) > max_chars:
            remaining = len(rows) - index + 1
            blocks.append(f"(입력 길이 제한으로 나머지 {remaining}건은 제외됨)")
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def extract_text(message) -> str:
    """응답에서 text 블록만 모아 반환.

    content[0]이 text라고 가정하면 안 된다 - 적응형 사고가 켜진 모델은
    thinking 블록을 먼저 내보내고 그 블록에는 .text가 없다. 거절(refusal)과
    max_tokens 절단도 여기서 걸러야, 잘린 반쪽 보고가 고객 텔레그램으로
    나가는 일을 막을 수 있다.
    """
    if message.stop_reason == "refusal":
        category = getattr(message.stop_details, "category", None)
        raise RuntimeError(
            f"모델이 요청을 거절했습니다 (category={category}). 프롬프트나 입력 데이터를 확인하세요."
        )
    if message.stop_reason == "max_tokens":
        raise RuntimeError(
            "응답이 max_tokens에서 잘렸습니다. 잘린 보고는 발송하지 않습니다. "
            "prompt.max_tokens를 올리거나 수집 건수(source.limit)를 줄이세요."
        )
    texts = [block.text for block in message.content if block.type == "text"]
    if not texts:
        raise RuntimeError(f"응답에 text 블록이 없습니다 (stop_reason={message.stop_reason})")
    return "".join(texts)


def build_prompt(job: JobSpec, rows: list[dict], now: dt.datetime) -> str:
    local_now = now.astimezone(ZoneInfo(job.schedule.timezone))
    return render(
        job.prompt.user_template,
        {
            "rows": rows_to_text(rows, job.max_input_chars),
            "row_count": str(len(rows)),
            "date": local_now.strftime("%Y-%m-%d"),
            "time": local_now.strftime("%H:%M"),
            "job_title": job.title,
        },
    )


def generate(job: JobSpec, rows: list[dict], now: dt.datetime, client=None) -> str:
    """잡 프롬프트로 보고서 본문 생성. client는 테스트에서 주입한다."""
    api_key = require_env("ANTHROPIC_API_KEY", "Claude 콘텐츠 생성")
    client = client or anthropic.Anthropic(api_key=api_key)

    params: dict = {
        "model": job.prompt.model,
        "max_tokens": job.prompt.max_tokens,
        "system": job.prompt.system,
        "messages": [{"role": "user", "content": build_prompt(job, rows, now)}],
    }
    if job.prompt.effort:
        params["output_config"] = {"effort": job.prompt.effort}

    return extract_text(client.messages.create(**params))
