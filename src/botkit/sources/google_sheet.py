"""구글 시트를 gviz CSV 엔드포인트로 읽는다 (OAuth 없이 공개 보기 링크만 사용)."""
from __future__ import annotations

import csv
import io
from urllib.parse import quote

import httpx

from botkit.jobspec import GoogleSheetSource

GVIZ_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
TIMEOUT = 30.0


def build_url(source: GoogleSheetSource) -> str:
    url = GVIZ_URL.format(sheet_id=source.sheet_id)
    if source.gid:
        return f"{url}&gid={source.gid}"
    if source.sheet_name:
        return f"{url}&sheet={quote(source.sheet_name)}"
    return url


def parse_csv(text: str) -> list[dict]:
    """CSV 본문을 행 목록으로. 시트의 실제 행 번호를 _row로 붙여준다.

    _row는 "스프레드시트 12행에 답변을 채워주세요"처럼 결과 메시지에서 위치를
    지목할 때 쓴다. 헤더가 1행이므로 데이터 첫 행은 2행이다.
    """
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    for index, raw in enumerate(reader):
        row = {
            (key or "").strip(): (value or "").strip()
            for key, value in raw.items()
            if key is not None
        }
        row["_row"] = index + 2
        rows.append(row)
    return rows


def check_columns(rows: list[dict], source: GoogleSheetSource) -> None:
    """필터가 가리키는 열이 실제로 시트에 있는지 확인.

    없는 열을 where_empty에 적으면 모든 행이 통과하고(전체 재발송),
    where_equals에 적으면 모든 행이 걸러진다(조용히 0건). 둘 다 조용한
    오작동이라 헤더 오타는 여기서 잡아야 한다 - 한글 열 이름은 특히 잘 틀린다.
    """
    if not rows:
        return
    available = {key for key in rows[0] if key != "_row"}
    referenced = set(source.where_empty) | set(source.where_equals)
    missing = sorted(referenced - available)
    if missing:
        raise RuntimeError(
            f"시트에 없는 열을 필터로 지정했습니다: {missing}. "
            f"실제 열 이름: {sorted(available)}"
        )


def apply_filters(rows: list[dict], source: GoogleSheetSource) -> list[dict]:
    check_columns(rows, source)
    selected = []
    for row in rows:
        if any(str(row.get(column, "")).strip() for column in source.where_empty):
            continue
        if any(str(row.get(k, "")).strip() != v for k, v in source.where_equals.items()):
            continue
        # 모든 값이 빈 행(시트 하단의 여백)은 버린다.
        if not any(str(v).strip() for k, v in row.items() if k != "_row"):
            continue
        selected.append(row)
    return selected[: source.limit]


def fetch_google_sheet(source: GoogleSheetSource) -> list[dict]:
    url = build_url(source)
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        response = client.get(url)
    if response.status_code in (401, 403, 404) or response.text.lstrip().startswith("<"):
        # 공개 설정이 안 된 시트는 CSV가 아니라 로그인 HTML을 돌려준다.
        # 이 실패가 납품 직후 1순위 원인이라 조치 방법까지 적어둔다.
        raise RuntimeError(
            f"구글 시트를 CSV로 읽지 못했습니다 (status={response.status_code}). "
            "시트 공유 설정을 '링크가 있는 모든 사용자 - 뷰어'로 바꾸고, "
            f"sheet_id({source.sheet_id})와 gid/sheet_name이 맞는지 확인하세요."
        )
    response.raise_for_status()
    return apply_filters(parse_csv(response.text), source)
