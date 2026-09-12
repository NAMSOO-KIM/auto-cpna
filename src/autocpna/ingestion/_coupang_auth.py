"""쿠팡파트너스 오픈 API 공통 인증/요청 로직 (내부용, 커넥터 간 공유).

인증 방식: HMAC-SHA256 서명 (쿠팡파트너스 오픈 API 공식 문서 기준).
"""
from __future__ import annotations

import hashlib
import hmac
import datetime as dt
from urllib.parse import urlencode

import httpx

BASE_URL = "https://api-gateway.coupang.com"
API_PREFIX = "/v2/providers/affiliate_open_api/apis/openapi/v1"


def signed_date() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%y%m%dT%H%M%SZ")


def generate_hmac_signature(
    method: str, path_with_query: str, secret_key: str, access_key: str, date: str
) -> str:
    """쿠팡파트너스 API 요청 서명 생성 (공식 문서의 HMAC 알고리즘).

    서명 대상 메시지는 signed-date + method + path + querystring이다.
    쿼리스트링이 있는 요청(예: 상품 검색, 리포트 조회)에서 쿼리스트링을
    빠뜨리면 서명이 어긋나 항상 401을 반환하므로 path에는 반드시
    쿼리스트링까지 포함시켜야 한다.
    """
    message = date + method + path_with_query
    signature = hmac.new(
        secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return (
        f"CEA algorithm=HmacSHA256, access-key={access_key}, "
        f"signed-date={date}, signature={signature}"
    )


def authenticated_get(path: str, params: dict, access_key: str, secret_key: str) -> dict:
    path_with_query = f"{path}?{urlencode(params)}" if params else path
    headers = {
        "Authorization": generate_hmac_signature(
            "GET", path_with_query, secret_key, access_key, signed_date()
        ),
        "Content-Type": "application/json;charset=UTF-8",
    }
    with httpx.Client(base_url=BASE_URL) as client:
        resp = client.get(path_with_query, headers=headers)
        resp.raise_for_status()
        return resp.json()
