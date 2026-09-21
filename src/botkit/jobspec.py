"""고객사 잡 정의(config/jobs/*.yaml) 스키마와 로더.

YAML을 pydantic으로 강하게 검증하는 이유: 이 파일을 고치는 사람은 납품 당일의
나 자신이고, 오타는 새벽 스케줄 실행 때 조용히 터진다. `botkit validate`가
납품 전에 잡아내도록 스키마를 좁게 잡았다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

JOBS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "jobs"

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Strict(BaseModel):
    """오타 난 키를 조용히 무시하지 않도록 모든 스키마의 공통 베이스.

    extra="forbid"가 없으면 `sytem:`처럼 한 글자 틀린 키가 기본값으로 대체돼
    '프롬프트를 고쳤는데 결과가 그대로'인 상황이 된다."""

    model_config = ConfigDict(extra="forbid")


class ScheduleSpec(Strict):
    """"고객사 현지 시각 기준 하루 N회" 정도만 표현하는 최소 스케줄.

    GitHub Actions cron은 UTC 고정이라 고객에게 "아침 8시"를 설명하기 어렵다.
    워크플로는 매시 정각에 한 번만 돌리고, 어떤 잡을 실행할지는 이 스펙과
    botkit.schedule이 고객사 타임존 기준으로 판단한다.
    """

    timezone: str = "Asia/Seoul"
    times: list[str] = Field(min_length=1)
    weekdays: list[str] | None = None

    @field_validator("times")
    @classmethod
    def _check_times(cls, times: list[str]) -> list[str]:
        for value in times:
            hour, _, minute = value.partition(":")
            if not (hour.isdigit() and minute.isdigit()):
                raise ValueError(f"times는 'HH:MM' 형식이어야 합니다: {value!r}")
            if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
                raise ValueError(f"times 범위를 벗어났습니다: {value!r}")
        return times

    @field_validator("weekdays")
    @classmethod
    def _check_weekdays(cls, days: list[str] | None) -> list[str] | None:
        if days is None:
            return None
        lowered = [d.lower() for d in days]
        unknown = [d for d in lowered if d not in WEEKDAYS]
        if unknown:
            raise ValueError(f"weekdays는 {WEEKDAYS} 중에서 골라야 합니다: {unknown}")
        return lowered


class GoogleSheetSource(Strict):
    """공개(링크가 있는 모든 사용자 - 뷰어) 구글 시트를 CSV로 읽는다.

    서비스 계정 키를 고객사마다 발급받는 과정이 납품 시간을 통째로 잡아먹어서,
    표준 납품은 '보기 전용 공개 링크 + gviz CSV' 경로만 쓴다. 비공개 시트가
    필요하면 딜럭스 작업(Apps Script 웹앱 -> http_json)으로 올린다.
    """

    type: Literal["google_sheet"]
    sheet_id: str
    sheet_name: str | None = None
    gid: str | None = None
    where_empty: list[str] = []
    where_equals: dict[str, str] = {}
    limit: int = 50


class RssSource(Strict):
    """RSS/Atom 피드. 네이버 뉴스·구글 뉴스 키워드 알림이 전부 이 경로로 들어온다."""

    type: Literal["rss"]
    feeds: list[str] = Field(min_length=1)
    since_hours: int | None = 24
    limit: int = 30
    summary_chars: int = 400


class HttpJsonSource(Strict):
    """임의의 JSON 엔드포인트. 고객사 자체 어드민/Apps Script 웹앱 연동용."""

    type: Literal["http_json"]
    url: str
    method: Literal["GET", "POST"] = "GET"
    headers: dict[str, str] = {}
    json_body: dict | None = None
    items_path: str = ""
    fields: list[str] = []
    limit: int = 50


class StaticSource(Strict):
    """YAML에 직접 적어둔 고정 목록(모니터링 키워드 등)."""

    type: Literal["static"]
    rows: list[dict] = Field(min_length=1)


SourceSpec = Annotated[
    GoogleSheetSource | RssSource | HttpJsonSource | StaticSource,
    Field(discriminator="type"),
]


class TelegramSink(Strict):
    type: Literal["telegram"]
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"
    # 기본값 none: LLM이 쓴 본문의 *, _, [ 가 Telegram 마크다운 파서에 걸려
    # 400으로 통째로 반송되는 사고가 가장 흔하다. 서식이 꼭 필요한 고객만 켠다.
    parse_mode: Literal["none", "Markdown", "MarkdownV2", "HTML"] = "none"
    disable_web_page_preview: bool = True
    header: str = ""


class WebhookSink(Strict):
    """슬랙 incoming webhook, 노션 프록시, 고객사 어드민 등 범용 POST."""

    type: Literal["webhook"]
    url_env: str
    text_key: str = "text"
    extra_payload: dict = {}
    headers: dict[str, str] = {}


SinkSpec = Annotated[TelegramSink | WebhookSink, Field(discriminator="type")]


class PromptSpec(Strict):
    """납품 때 실제로 손대는 유일한 부분."""

    system: str
    user_template: str
    model: str = "claude-opus-5"
    max_tokens: int = 16000
    # 비워두면 API 기본값(high). 매일 도는 요약 잡의 비용을 낮추고 싶을 때만
    # low/medium으로 내린다 - 품질 저하 여부는 고객 데이터로 먼저 확인할 것.
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None

    @field_validator("user_template")
    @classmethod
    def _requires_rows(cls, template: str) -> str:
        if "{rows}" not in template:
            raise ValueError(
                "user_template에는 수집 결과가 들어갈 자리인 {rows}가 반드시 있어야 합니다."
            )
        return template


class JobSpec(Strict):
    name: str = ""
    title: str
    enabled: bool = True
    schedule: ScheduleSpec
    source: SourceSpec
    prompt: PromptSpec
    sinks: list[SinkSpec] = Field(min_length=1)
    # 수집 결과가 0건이면 "오늘은 새 글이 없습니다" 같은 빈 보고를 보내느라
    # API 비용을 쓰지 않는다. 매일 결과가 와야 안심하는 고객은 false로 바꾼다.
    skip_when_empty: bool = True
    max_input_chars: int = 40000


class JobConfigError(RuntimeError):
    """YAML 파싱/검증 실패. 어느 파일의 어느 키가 문제인지까지 담는다."""


def parse_job(name: str, data: dict) -> JobSpec:
    try:
        spec = JobSpec.model_validate({**data, "name": data.get("name") or name})
    except ValidationError as exc:
        details = "\n".join(
            f"  - {'.'.join(str(p) for p in err['loc']) or '(최상위)'}: {err['msg']}"
            for err in exc.errors()
        )
        raise JobConfigError(f"{name}.yaml 설정 오류:\n{details}") from exc
    return spec


def load_job_file(path: Path) -> JobSpec:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise JobConfigError(f"{path.name}: 최상위가 매핑(key: value)이 아닙니다.")
    return parse_job(path.stem, data)


def load_jobs(jobs_dir: Path | None = None) -> list[JobSpec]:
    """config/jobs/*.yaml 전체를 이름순으로 로드.

    한 파일이 깨져도 나머지를 로드하지 않고 즉시 실패시킨다 - 스케줄러가
    '설정이 깨진 고객사만 조용히 빠진 채' 정상 종료하는 쪽이 더 위험하다.
    """
    directory = jobs_dir or JOBS_DIR
    if not directory.exists():
        return []
    paths = sorted(p for p in directory.glob("*.yaml") if not p.name.startswith("_"))
    return [load_job_file(path) for path in paths]


def load_job(name: str, jobs_dir: Path | None = None) -> JobSpec:
    directory = jobs_dir or JOBS_DIR
    path = directory / f"{name}.yaml"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in directory.glob("*.yaml"))) or "(없음)"
        raise JobConfigError(f"잡 '{name}'을(를) 찾을 수 없습니다. 사용 가능: {available}")
    return load_job_file(path)
