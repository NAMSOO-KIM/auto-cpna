"""텔레그램 발송. 고객이 실제로 보는 결과물이 나가는 지점."""
from __future__ import annotations

import time

import httpx

from botkit.jobspec import TelegramSink
from botkit.settings import require_env

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 30.0
# 텔레그램 한 메시지 상한은 4096자다. 이모지/한글은 UTF-16 코드유닛으로 계산되는
# 데다 서식 태그도 길이에 포함돼, 상한에 붙여서 자르면 간헐적으로 반송된다.
CHUNK_LIMIT = 3500


class TelegramSendError(RuntimeError):
    """뒤 청크가 실패해도 앞 청크의 발송 증거를 버리지 않는다."""

    def __init__(self, message: str, message_ids: list[int]):
        super().__init__(message)
        self.message_ids = list(message_ids)


def split_message(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """길이 상한에 맞춰 나눈다. 문단 -> 줄 -> 강제 절단 순으로 경계를 찾는다."""
    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    chunks.append(remaining)
    return [chunk for chunk in chunks if chunk]


def _error_detail(response: httpx.Response) -> str:
    """텔레그램이 알려준 실패 사유("chat not found" 등).

    봇 토큰은 URL에만 있고 응답 바디에는 없다. 그래서 httpx 예외 문자열은
    가리되(send의 except 참고) 이 description은 그대로 보여준다 - 납품 직후
    장애의 실제 원인이 대부분 이 한 줄에 들어 있다.
    """
    try:
        return str(response.json().get("description") or response.text)[:300]
    except ValueError:
        return response.text[:300]


def _post(client: httpx.Client, url: str, payload: dict) -> httpx.Response:
    """429(rate limit)만 한 번 재시도한다. 여러 청크를 연속 발송할 때 걸린다."""
    response = client.post(url, json=payload)
    if response.status_code == 429:
        try:
            retry_after = int(response.json()["parameters"]["retry_after"])
        except (ValueError, KeyError, TypeError):
            retry_after = 3
        time.sleep(min(retry_after, 30))
        response = client.post(url, json=payload)
    return response


def send(sink: TelegramSink, text: str, header: str = "") -> list[int]:
    """메시지를 보내고 message_id 목록을 반환."""
    token = require_env(sink.bot_token_env, "텔레그램 봇 토큰 (@BotFather 발급)")
    chat_id = require_env(sink.chat_id_env, "텔레그램 채팅 ID (@userinfobot 또는 그룹 ID)")
    url = API_URL.format(token=token)

    body = f"{header}\n\n{text}" if header else text
    message_ids: list[int] = []
    with httpx.Client(timeout=TIMEOUT) as client:
        for chunk in split_message(body):
            payload: dict = {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": sink.disable_web_page_preview,
            }
            if sink.parse_mode != "none":
                payload["parse_mode"] = sink.parse_mode

            try:
                response = _post(client, url, payload)
                if response.status_code == 400 and "parse_mode" in payload:
                    # LLM 본문의 *, _, [ 가 마크다운 파서에 걸려 반송된 경우.
                    # 서식을 포기하고 평문으로 다시 보낸다 - 서식 때문에 보고가
                    # 아예 안 가는 것보다 낫다.
                    payload.pop("parse_mode")
                    response = _post(client, url, payload)
                if response.status_code != 200:
                    raise TelegramSendError(
                        f"텔레그램 발송 실패 (status={response.status_code}): "
                        f"{_error_detail(response)}. "
                        f"봇 초대 여부와 {sink.chat_id_env} 설정을 확인하세요.", message_ids
                    )
                data = response.json()
                message_id = data.get("result", {}).get("message_id")
                if data.get("ok") is not True or type(message_id) is not int or message_id <= 0:
                    raise TelegramSendError("텔레그램 응답에 유효한 message_id가 없습니다.", message_ids)
                message_ids.append(message_id)
            except TelegramSendError:
                raise
            except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
                # URL에 bot token이 들어 있어 원본 네트워크 예외를 출력하면 안 된다.
                raise TelegramSendError(
                    f"텔레그램 통신/응답 오류 ({type(exc).__name__}). "
                    "발송 여부를 확인한 후 재시도하세요.", message_ids
                ) from exc
    return message_ids
