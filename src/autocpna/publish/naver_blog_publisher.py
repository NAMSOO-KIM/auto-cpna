"""네이버 블로그는 공식 자동 포스팅 API가 없음.

자동화 도구로 글을 올리면 네이버 어뷰징 정책 위반으로 계정 정지 위험이 크므로,
이 Publisher는 절대 자동 발행하지 않고 초안을 사람이 복사해 붙여넣을 수 있는
형태로 로컬에 내보내기만 한다. config/channels.yaml의 naver_blog.auto_publish도
false로 고정되어 있어 orchestrator가 이 경로를 자동으로 타지 않는다.
"""
from __future__ import annotations

from pathlib import Path

from autocpna.publish.base import PublishResult, Publisher

EXPORT_DIR = Path("media_output/naver_blog_drafts")


class NaverBlogPublisher(Publisher):
    channel = "naver_blog"

    def publish(self, draft) -> PublishResult:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = EXPORT_DIR / f"draft_{draft.id}.txt"
        out_path.write_text(draft.caption_or_body, encoding="utf-8")
        return PublishResult(
            success=False,
            error_message=(
                "네이버 블로그는 자동 발행을 지원하지 않습니다. 검수 대시보드의 "
                "'네이버 블로그 수동 발행 대기'에서 본문을 받아 직접 게시한 뒤 "
                "'발행 완료로 표시'를 누르세요. "
                f"(로컬 실행 시에는 {out_path} 에도 저장됨)"
            ),
        )
