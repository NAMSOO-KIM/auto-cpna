# AGENTS.md — auto-cpna

이 저장소는 **쿠팡파트너스 / 네이버 제휴 콘텐츠 파이프라인**(`src/autocpna`)이다.
수집 → 스코어링 → 채널별 콘텐츠 생성 → 검수 → 발행을 담당하고, Streamlit 대시보드
(`dashboard/app.py`)로 검수한다.

```bash
pip install -e ".[dev]"
ruff check .
pytest -q
```

## 여기 없는 것

크몽 판매용 업무 자동화 봇 보일러플레이트(`botkit`)는 **별도 상품**이라
`https://github.com/NAMSOO-KIM/botkit` 저장소로 분리했다. 그 작업 지시서와 작업 큐는
그쪽 `AGENTS.md`에 있다. 이 저장소에서 botkit 작업을 하지 마라 — 두 제품은 코드를
공유하지 않는다.

분리 전 이력(botkit 도입 ~ P0-2)은 이 저장소의
`claude/ai-bot-automation-monetization-vimz44` 브랜치에 남아 있다.
