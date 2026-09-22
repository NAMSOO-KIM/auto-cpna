"""botkit이 쓰는 환경변수 접근 지점.

키는 전부 환경변수(GitHub Actions Secrets)로만 받는다. 고객사 토큰이
config/jobs/*.yaml에 절대 들어가지 않도록, YAML에는 값이 아니라 "환경변수
이름"만 적게 하고 여기서 이름 -> 값으로 해석한다.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


CLIENT_ID_RE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*\Z")
ENV_NAME_RE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*\Z")


def check_client_id(client_id: str) -> str:
    """대소문자/구분자 정규화로 서로 다른 고객이 같은 namespace가 되는 일을 막는다."""
    if not isinstance(client_id, str) or len(client_id) > 64 or not CLIENT_ID_RE.fullmatch(client_id):
        raise ValueError("client_id는 대문자로 시작하는 영문 대문자/숫자/단일 _ 조합(64자 이하)입니다.")
    return client_id


def client_env_candidates(name: str, client_id: str) -> tuple[str, str]:
    """이 고객의 이름과 공용 이름만 만든다. 다른 고객 이름은 조회조차 하지 않는다."""
    check_client_id(client_id)
    base, separator, owner = name.partition("__")
    if not ENV_NAME_RE.fullmatch(base) or len(base) > 128:
        raise ValueError("시크릿 설정에는 유효한 대문자 환경변수 이름을 사용하세요.")
    if separator and owner != client_id:
        raise ValueError("다른 고객의 시크릿 namespace를 참조할 수 없습니다.")
    return f"{base}__{client_id}", base


@dataclass(frozen=True)
class SecretSelection:
    """진단용 메타데이터에 값은 넣지 않는다 (repr/validate 로그에도 값 노출 없음)."""

    scoped_name: str
    shared_name: str
    selected_name: str | None

    @property
    def fallback(self) -> bool:
        return self.selected_name is not None and self.selected_name == self.shared_name


def select_client_secret(name: str, client_id: str) -> SecretSelection:
    scoped, shared = client_env_candidates(name, client_id)
    # Actions에서 등록하지 않은 Secrets도 빈 문자열 env로 들어오므로 공백도 없는 값으로 본다.
    selected = next((key for key in (scoped, shared) if os.environ.get(key, "").strip()), None)
    return SecretSelection(scoped, shared, selected)


class MissingSecretError(RuntimeError):
    """필요한 환경변수가 비어 있을 때. 납품 직후 가장 흔한 실패라서
    '무엇을 어디에 넣어야 하는지'까지 메시지에 담는다."""


def require_env(name: str, purpose: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingSecretError(
            f"환경변수 {name}이(가) 비어 있습니다 ({purpose}). "
            f"로컬은 .env, GitHub Actions는 Settings > Secrets and variables > "
            f"Actions에 {name}을(를) 등록하세요."
        )
    return value


def optional_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


def resolve_env_reference(value: str) -> str:
    """헤더 값 등에 쓰는 "env:NAME" 표기를 실제 값으로 바꾼다.

    고객사 API 키가 들어가는 자리(Authorization 헤더 등)를 YAML에 평문으로
    적지 않게 하려는 장치다. "env:" 접두사가 없으면 평문 그대로 쓴다.
    """
    if value.startswith("env:"):
        name = value[len("env:") :].strip()
        return require_env(name, f"요청 헤더에 사용됨 (env:{name})")
    return value


def load_env_file(path: str = ".env") -> int:
    """로컬 실행 편의를 위한 최소 .env 로더. 반환값은 새로 넣은 키 개수.

    python-dotenv를 추가하지 않는 이유는 납품본을 가볍게 유지하기 위해서다.
    이미 설정된 환경변수는 덮어쓰지 않는다 - GitHub Actions Secrets로 들어온
    값이 리포지터리에 남은 옛날 .env에 밀려나면 추적이 매우 어려워진다.
    """
    file_path = Path(path)
    if not file_path.exists():
        return 0

    loaded = 0
    for line in file_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")
        loaded += 1
    return loaded
