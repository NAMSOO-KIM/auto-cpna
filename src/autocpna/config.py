"""환경변수 + YAML 설정 로더."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""

    coupang_partners_access_key: str = ""
    coupang_partners_secret_key: str = ""
    coupang_partners_vendor_id: str = ""

    # NAVER API HUB(NCP 콘솔)에서 발급하는 검색어 트렌드 API 키
    naver_datalab_client_id: str = ""
    naver_datalab_client_secret: str = ""

    meta_page_access_token: str = ""
    meta_ig_business_id: str = ""
    meta_threads_user_id: str = ""

    image_gen_api_key: str = ""

    database_url: str = "sqlite:///./autocpna.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def get_channels_config() -> dict:
    return _load_yaml("channels.yaml")


@lru_cache
def get_personas_config() -> dict:
    return _load_yaml("personas.yaml")


@lru_cache
def get_scoring_weights() -> dict:
    return _load_yaml("scoring_weights.yaml")
