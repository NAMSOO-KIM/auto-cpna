# 크몽/숨고 판매용 AI 업무 자동화 봇 - 상품 구현 지시서

> **이 문서의 목적**: Codex(또는 다른 AI 코딩 에이전트)가 기존 코드를 조사·재사용해
> 이 상품의 남은 부분을 구현하도록 지시하는 단일 진입 문서.
> 새로 처음부터 만들지 말 것. 아래 저장소에 **이미 동작하는 골격이 있다.**

| 항목 | 값 |
| --- | --- |
| 문서 작성일 | 2026-09-22 |
| 상품명 | 맞춤형 업무 자동화 AI 텔레그램 봇 구축 |
| 구현 기준 저장소 | `https://github.com/NAMSOO-KIM/auto-cpna` |
| 작업 브랜치 | `claude/ai-bot-automation-monetization-vimz44` |
| 기준 커밋 | `f170ba8` (botkit 도입 3개 커밋: `a6bbee3` → `ff7f55d` → `f170ba8`) |
| 언어/런타임 | Python 3.11 |
| 현재 상태 | 표준(Standard) 등급 납품 가능. 딜럭스/프리미엄 등급 기능은 미구현 |

---

## 0. 저장소 지정 (Codex가 가장 먼저 할 일)

### GitHub URL

```
https://github.com/NAMSOO-KIM/auto-cpna
```

### 로컬 클론

```powershell
# 이 문서가 있는 작업 폴더 기준 권장 위치
cd C:\Users\admin\Documents\Codex\2026-09-22\lead-developer-automation-engineer-qa-release
git clone https://github.com/NAMSOO-KIM/auto-cpna.git
cd auto-cpna
git checkout claude/ai-bot-automation-monetization-vimz44
```

### 개발 환경 준비 및 현황 확인

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

ruff check .          # 통과해야 함
pytest -q             # 165개 통과 (botkit 관련 68개)
botkit list           # 예시 잡 3개가 보이면 정상
```

> **주의**: 이 저장소는 원래 쿠팡파트너스/네이버 제휴 콘텐츠 파이프라인(`src/autocpna`)
> 프로젝트다. 이번 상품의 코드는 **`src/botkit`** 이며, `autocpna`를 import 하지 않는다
> (고객사 저장소로 떼어내기 위한 의도적 분리). 이 경계를 깨지 말 것.

---

## 1. 상품 정의

### 파는 것

"매일 2시간 걸리는 엑셀/데이터 수작업을, 맞춤형 AI 텔레그램 봇으로 자동화" —
고객은 웹사이트나 크롤러를 원하는 것이 아니라 **퇴근 시간을 앞당겨줄 직원**을 원한다.

### 동작 구조

```
데이터 소스                     처리                    결과
구글시트 / RSS / JSON API  →  Claude API  →  텔레그램 / 슬랙
        └─────── GitHub Actions(매시 정각 스케줄) ───────┘

고객사별 차이 = config/jobs/<고객사>.yaml 한 장 (코드 수정 없음)
```

### 핵심 제약 (설계 원칙 — 변경 시 상품성이 깨짐)

1. **납품 1건에서 새로 쓰는 파일은 YAML 한 장.** 파이썬을 열어야 하는 건은
   표준 등급이 아니다. 새 기능은 반드시 "YAML 옵션"으로 노출되어야 한다.
2. **`src/botkit`은 독립적이어야 한다.** `autocpna`, SQLAlchemy, DB에 의존 금지.
   의존 패키지는 `anthropic`, `httpx`, `pydantic`, `pyyaml`, `click` 5개로 제한.
3. **초안까지만.** 봇은 사람에게 결과를 보내는 것으로 끝난다. 고객 명의로 외부에
   자동 게시/발송하는 기능은 별도 계약 없이 추가하지 않는다.
4. **조용한 실패 금지.** 잘린 응답, 열 이름 오타, 시크릿 누락은 전부 명시적 에러로
   터져야 한다. 아래 4장의 "이미 막아둔 실패 모드"를 제거하지 말 것.

### 판매 등급과 구현 상태

| 등급 | 가격 | 제공 내용 | 현재 상태 |
| --- | --- | --- | --- |
| Standard | 50~80만 원 | 시트/RSS → Claude → 텔레그램, 프롬프트 맞춤 | **구현 완료** |
| Deluxe | 150~200만 원 | 외부 시스템 연동(슬랙/어드민 API), 시트 되쓰기, 데이터 축적 | 부분 구현 (P0/P1 필요) |
| Premium | 월 10~30만 원 | 서버·토큰 관리, 프롬프트 업데이트, 장애 대응 | 운영 도구 미비 (P0 필요) |

---

## 2. 기존 코드 자산 지도 (재사용 대상)

Codex는 아래 파일을 **먼저 전부 읽고** 구조를 파악한 뒤 작업을 시작한다.
총 약 1,200줄이며 한국어 주석에 각 설계 판단의 근거가 남아 있다.

### 코드 (`src/botkit/`, 재사용 필수)

| 파일 | 역할 | 확장 시 손댈 지점 |
| --- | --- | --- |
| `jobspec.py` | 잡 YAML 스키마(pydantic). 소스/싱크는 `type` 판별 유니온 | **새 소스/싱크 추가 시 여기 모델 추가** |
| `schedule.py` | 고객사 타임존 기준 "지금 보낼 잡인가" 판정 (tick 윈도우) | 스케줄 표현력 확장 |
| `state.py` | 마지막 실행 회차 기록(JSON) → 중복 발송 방지 | 발송 이력 확장 시 참고 |
| `runner.py` | 수집 → 생성 → 발송 오케스트레이션, 잡 단위 실패 격리 | 비용 계측·이력 기록 삽입 지점 |
| `llm.py` | Claude 호출, 프롬프트 렌더링, 응답 검증 | usage 토큰 수집 지점 |
| `settings.py` | 환경변수 해석(`env:NAME` 표기), `.env` 로더 | — |
| `sources/google_sheet.py` | 공개 시트 gviz CSV 읽기 + 행 필터 | 시트 **쓰기**는 여기 아님 (P1 참고) |
| `sources/rss.py` | RSS 2.0 / Atom 파싱, 기간 필터, 링크 중복 제거 | 네이버 API 소스 추가 시 패턴 참고 |
| `sources/http_json.py` | 임의 JSON 엔드포인트, `items_path` 점 표기 탐색 | Apps Script 연동의 기반 |
| `sinks/telegram.py` | 4096자 분할, parse_mode 실패 시 평문 재시도, 429 재시도 | 인바운드 명령은 여기 아님 (P1) |
| `sinks/webhook.py` | 범용 POST (슬랙 incoming webhook 등) | — |
| `cli.py` | `botkit list / validate / due / run / test-telegram` | 새 운영 명령 추가 지점 |

### 설정·배포

| 파일 | 역할 |
| --- | --- |
| `config/jobs/_TEMPLATE.yaml` | **납품 시 복사하는 원본.** 채울 곳 5개가 주석으로 표시됨 |
| `config/jobs/example_keyword_brief.yaml` | 상품① 마케터 모닝 브리핑 (RSS) |
| `config/jobs/example_cs_reply_draft.yaml` | 상품② CS 답변 초안 (구글 시트) |
| `config/jobs/example_competitor_watch.yaml` | 상품③ 경쟁사 알림 (JSON API) |
| `.github/workflows/botkit.yml` | 매시 정각 스케줄러 + 수동 실행 + 실패 시 운영자 알림 |
| `.github/workflows/ci.yml` | ruff + pytest (푸시마다 실행) |
| `.env.example` | 필요한 환경변수 전체 목록 |

### 문서 (읽고 나서 구현할 것)

| 파일 | 내용 |
| --- | --- |
| `docs/botkit.md` | 기술 문서: 잡 스키마 전체, 스케줄 동작 원리, 장애 대응표 |
| `docs/monetization-playbook.md` | 가격 정책, 원가 계산, 2시간 납품 절차, 온보딩 폼 항목 |

### 테스트 (68개, 회귀 방지선)

`tests/test_botkit_{jobspec,schedule,state,sources,llm,telegram,runner}.py` —
각 테스트의 docstring이 "왜 이 케이스가 존재하는가"를 설명한다.
**기존 테스트를 수정해서 통과시키는 방식은 금지.** 동작을 바꿔야 한다면 그 이유를
커밋 메시지에 남기고 테스트를 함께 갱신한다.

### 참고용 (직접 수정 금지)

`src/autocpna/**` — 다른 상품(제휴 콘텐츠 파이프라인). Claude 호출 패턴
(`content_gen/base.py`의 `extract_text`)과 httpx 사용 패턴만 참고한다.

---

## 3. 구현 요청 범위 (Codex 작업 목록)

우선순위 순. 각 항목은 독립 커밋 단위이며, **YAML 옵션으로 노출**되어야 한다.

### P0 — 구독(Premium) 상품을 팔기 위해 반드시 필요

#### P0-1. 발송 이력 및 비용 계측

> 구현 반영(2026-09-22): YAML `history` 옵션, 월별 JSONL, usage/단가 스냅샷,
> `botkit report`, 실패·dry-run 비용 및 부분 발송 ID 보존을 추가했다.
> 검증·릴리스 범위는 [P0-1 릴리스 기록](docs/releases/p0-1.md) 참고.
> 본문 재열람/승인 전달은 아직 미구현이며 P0-3 범위다.

- **문제**: 지금은 무엇을 언제 보냈는지 기록이 없다. 고객이 "지난주 화요일 보고 다시
  보여달라"고 하면 답할 수 없고, 구독 원가(토큰 사용량)도 측정 불가하다.
- **구현**:
  - `runner.py`에서 실행 1건마다 JSONL 1줄 추가 (`.botkit/history/<YYYY-MM>.jsonl`)
  - 기록 필드: `job_name`, `fire_at`, `finished_at`, `status`, `row_count`,
    `input_tokens`, `output_tokens`, `estimated_cost_usd`, `message_ids`, `error`
  - `llm.py`에서 `response.usage`의 `input_tokens` / `output_tokens`를 반환값에
    함께 실어 보낸다 (현재는 텍스트만 반환 → 반환 타입을 dataclass로 변경)
  - 단가는 `config/pricing.yaml`에 모델별로 두고 코드에 하드코딩하지 않는다
  - 신규 CLI: `botkit report --month 2026-09` → 잡별 실행 횟수/토큰/추정 비용 표
- **수용 기준**: 한 달 실행 후 `botkit report`가 잡별 원가를 보여주고, 그 값으로
  구독가 대비 마진을 판단할 수 있다.

#### P0-2. 고객사별 시크릿 격리

- **문제**: 지금은 한 저장소의 여러 잡이 `TELEGRAM_BOT_TOKEN` 하나를 공유한다.
  고객 A의 봇 토큰으로 고객 B에게 보낼 수 있는 구조이며, 고객 하나가 토큰을
  교체하면 전체가 영향을 받는다.
- **구현**:
  - 잡 YAML에 `client_id` 필수 필드 추가
  - 시크릿 이름 규칙 확립: `TELEGRAM_BOT_TOKEN__<CLIENT_ID>` 우선, 없으면 공용
    `TELEGRAM_BOT_TOKEN` 폴백 (기존 잡 호환)
  - `botkit validate`가 잡별로 어떤 시크릿 이름을 해석했는지 출력
  - `docs/botkit.md`에 "고객사 1곳 = 저장소 1개"를 권장 운영 형태로 명시하고,
    한 저장소 다중 고객 운영 시의 위험을 적는다
- **수용 기준**: 고객 A의 잡이 고객 B의 토큰을 절대 참조할 수 없음을 테스트로 증명.

#### P0-3. 발송 전 미리보기 승인 모드 (선택 가능)

- **문제**: 신규 고객은 첫 1~2주간 "AI가 뭘 보낼지 모르는 상태"를 불안해한다.
  현재는 즉시 발송뿐이다.
- **구현**:
  - 잡 YAML에 `approval: {mode: auto | operator_first}` 추가
  - `operator_first`면 고객 채널 대신 운영자 채널(`OPS_TELEGRAM_CHAT_ID`)로 먼저
    보내고, 본문 머리에 `[검수 대기]` 표시 + 원문 그대로 복사 가능하게 발송
  - 운영자가 확인 후 `botkit forward --job X --history-id <id>`로 고객 채널로 전달
- **수용 기준**: 검수 모드에서는 고객 채널로 어떤 메시지도 나가지 않는다(테스트).

### P1 — 딜럭스 등급 납품에 필요

#### P1-1. 구글 시트 되쓰기 (Apps Script 웹앱 경로)

- **문제**: CS 상품의 완성형은 "답변 초안을 시트 D열에 채워주기"인데, 현재는
  텔레그램으로만 보낸다(고객이 복사·붙여넣기 해야 함).
- **구현**:
  - `sinks/google_sheet_writeback.py` 신규: `http_json` 소스와 대칭되는 `webhook`
    변형. Apps Script 웹앱(`doPost`)에 `{row, column, value}` 배열을 POST
  - 배포용 Apps Script 코드 전문을 `docs/apps-script/writeback.gs`로 함께 제공
    (고객이 시트에서 확장 프로그램 → Apps Script에 붙여넣고 배포하면 끝)
  - LLM 출력에서 행별 값을 파싱해야 하므로, 프롬프트에 구조화 출력을 요구하고
    파싱 실패 시 텔레그램 폴백으로 내려간다 (조용히 빈 값 쓰기 금지)
  - `docs/botkit.md`에 고객 온보딩 절차(웹앱 배포 5단계) 추가
- **수용 기준**: 시트에 문의 3건을 넣고 실행하면 D열에 초안 3건이 채워지고,
  파싱 실패 시 시트는 건드리지 않고 텔레그램으로만 나간다.

#### P1-2. 네이버 검색 API 소스

- **문제**: 한국 고객의 키워드 모니터링은 네이버 블로그/뉴스/카페가 본진인데
  현재 RSS(구글 뉴스)만 있다.
- **구현**:
  - `sources/naver_search.py` 신규. `sources/rss.py`의 구조를 그대로 따를 것
  - `src/autocpna/ingestion/naver_datalab.py`에 네이버 API 인증 헤더 처리 선례가
    있으니 **읽고 참고**하되 import 하지 말 것(경계 유지)
  - YAML: `{type: naver_search, targets: [blog, news], keywords: [...], display: 20, sort: date}`
  - 키는 `env:NAVER_CLIENT_ID` / `env:NAVER_CLIENT_SECRET` 표기 사용
- **수용 기준**: 키워드 2개 × 대상 2종으로 실행 시 중복 제거된 결과가 나오고,
  키 누락 시 "어디서 발급받아 어디에 넣어야 하는지"까지 담긴 에러가 난다.

#### P1-3. 텔레그램 인바운드 명령

- **문제**: 고객이 봇에게 말을 걸 수 없다. "지금 한 번 돌려줘", "이번 주는 쉬어"를
  전부 나에게 연락해야 하고, 그게 구독 운영 부담의 대부분이 된다.
- **구현**:
  - `webhook` 수신용 최소 엔드포인트(Vercel Functions 또는 Cloudflare Workers)
    + `botkit` 측 명령 핸들러 분리
  - 지원 명령: `/run`(즉시 1회), `/pause <일수>`, `/resume`, `/status`, `/help`
  - 명령 권한은 `chat_id` 화이트리스트로만 (고객이 남의 잡을 조작할 수 없어야 함)
  - `/pause`는 잡 YAML을 고치지 않고 상태 파일에 기록 (Git 커밋 없이 동작)
- **수용 기준**: 고객이 `/pause 3`을 보내면 3일간 발송이 멈추고, 운영자 개입 없이
  4일째 자동 재개된다.

### P2 — 여유 있을 때

- **P2-1 온보딩 자동화**: 구글 폼 응답(CSV) → 잡 YAML 초안 생성 스크립트
  (`botkit scaffold --from-form answers.csv`). 납품 시간을 2시간 → 1시간으로 줄인다.
- **P2-2 프롬프트 A/B 기록**: 프롬프트를 바꿨을 때 이전 버전 출력과 나란히 비교하는
  `botkit diff --job X --against <history-id>`. 구독 갱신 근거 자료로 쓴다.
- **P2-3 통합 테스트**: 실제 API를 호출하는 스모크 테스트를 `-m integration`으로
  분리하고 CI에서는 제외, 릴리스 전 수동 실행.
- **P2-4 다중 채널 라우팅**: 잡 결과를 조건에 따라 다른 채널로 (예: 긴급 키워드가
  포함되면 운영자 채널에도 동시 발송).

---

## 4. 건드리면 안 되는 것 (이미 막아둔 실패 모드)

이 목록은 실제 운영 사고를 근거로 넣은 방어 코드다. 리팩터링 중 제거되면
새벽 스케줄에서 조용히 터진다. **제거 금지, 우회 금지.**

| 방어 | 위치 | 제거 시 발생하는 사고 |
| --- | --- | --- |
| `extra="forbid"` 스키마 | `jobspec.py` | `sytem:` 같은 한 글자 오타가 기본값으로 대체 → "프롬프트를 고쳤는데 결과가 그대로" |
| 정규식 기반 플레이스홀더 치환 (`str.format` 금지) | `llm.py: render()` | 고객 프롬프트의 JSON 예시 중괄호가 `KeyError` → 스케줄 전체 사망 |
| `max_tokens` / `refusal` 응답 발송 차단 | `llm.py: extract_text()` | 잘린 반쪽 보고가 고객에게 발송 |
| thinking 블록 건너뛰기 | `llm.py: extract_text()` | `content[0].text` 가정 → `AttributeError` |
| `parse_mode` 기본값 `none` + 400 시 평문 재시도 | `sinks/telegram.py` | LLM 본문의 `*`, `_` 때문에 메시지 전체 반송 |
| 4096자 분할 (문단 → 줄 → 강제 절단) | `sinks/telegram.py` | 긴 보고가 발송 실패 |
| 시트 필터 열 이름 검증 | `sources/google_sheet.py: check_columns()` | `where_empty` 오타 → 전체 행 재발송 / `where_equals` 오타 → 조용히 0건 |
| 잡 단위 실패 격리 | `runner.py: run_due()` | 고객 A의 시트 공유 해제로 고객 B의 보고까지 누락 |
| 실패한 잡은 상태 미기록 | `runner.py: run_due()` | 일시 장애가 영구 누락으로 고정 |
| tick 윈도우 판정 | `schedule.py: due_at()` | Actions 지연 시 해당 회차 통째로 누락 |
| `.env`가 환경변수를 덮어쓰지 않음 | `settings.py: load_env_file()` | 저장소에 남은 옛 `.env`가 Actions Secrets를 무력화 |
| 실패 알림은 운영자 채널 전용 | `.github/workflows/botkit.yml` | 고객에게 에러 로그가 노출 |

---

## 5. QA 체크리스트 (릴리스 전 수동 확인)

### 코드 품질

- [ ] `ruff check .` 통과
- [ ] `pytest -q` 전체 통과 (기존 165개 + 신규)
- [ ] 신규 기능마다 테스트 추가. "왜 이 케이스인가"를 docstring에 남긴다
- [ ] `src/botkit`이 `autocpna`를 import 하지 않음:
      `grep -rE "^\s*(import|from)\s+autocpna" src/botkit/` 결과가 비어 있어야 함
      (주석·docstring의 언급은 정상이므로 `grep autocpna`만으로는 판정 불가)
- [ ] 의존성 5개 제한 유지: `grep -rE "^import |^from " src/botkit/` 검토

### 기능 (실제 자격증명으로 1회씩)

- [ ] `botkit validate` — 시크릿 누락 시 exit 1, 누락 목록이 정확
- [ ] `botkit test-telegram --job X` — 고객 채팅방에 도착
- [ ] `botkit run --job X --dry-run` — 발송 없이 본문만 출력
- [ ] `botkit run --job X` — 실제 발송, 4000자 넘는 본문도 분할 도착
- [ ] `botkit due` — 예정 시각 ±tick 안에서만 "실행 대상"
- [ ] 같은 회차 2회 실행 → 두 번째는 skipped (중복 발송 없음)
- [ ] 소스 강제 실패(잘못된 sheet_id) → 다른 잡은 정상 발송, 운영자 알림 도착
- [ ] 수집 0건 → API 호출 없이 skipped (비용 발생 없음)

### 보안 / 데이터

- [ ] `git grep -nE "(sk-ant|bot[0-9]{8,}:|AIza|xoxb-)"` → 결과 없음
- [ ] 잡 YAML에 토큰·URL 시크릿 평문 없음 (환경변수 이름만)
- [ ] 예시 잡 3개는 `enabled: false` 유지
- [ ] 에러 메시지에 토큰이 섞이지 않음 (특히 텔레그램 URL)
- [ ] 고객 개인정보(이름·연락처)를 다루는 잡은 `fields`/열 제한으로 최소 수집

### 문서

- [ ] `docs/botkit.md`에 신규 YAML 옵션 반영 (표에 항목 추가)
- [ ] `docs/monetization-playbook.md`의 등급별 제공 내용 갱신
- [ ] 신규 환경변수를 `.env.example`과 워크플로 `env:` 블록에 함께 추가
      (한쪽만 추가하면 로컬은 되고 Actions에서만 실패한다)

---

## 6. 릴리스 절차

```powershell
# 1. 작업 브랜치에서 개발
git checkout claude/ai-bot-automation-monetization-vimz44
git pull origin claude/ai-bot-automation-monetization-vimz44

# 2. 커밋 (기능 1개 = 커밋 1개, 메시지는 '왜'를 적는다)
git add <변경 파일>
git commit

# 3. 푸시 → CI(ruff + pytest)가 자동 실행
git push -u origin claude/ai-bot-automation-monetization-vimz44

# 4. CI 녹색 확인 후, 위 QA 체크리스트를 실제 자격증명으로 수행
```

### 고객 납품 릴리스 (상품 운영)

1. 고객사 전용 저장소 생성 (프라이빗)
2. `src/botkit/`, `config/jobs/<고객사>.yaml`, `.github/workflows/botkit.yml`,
   `pyproject.toml`, `.env.example` 복사 (DB·autocpna 관련 파일 제외)
3. Actions Secrets 등록: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, `OPS_TELEGRAM_CHAT_ID` (+ 잡이 참조하는 추가 키)
4. `botkit validate` → `test-telegram` → `run --dry-run` → `run` 순으로 리허설
5. 워크플로 수동 실행으로 스케줄 경로까지 1회 검증
6. 고객에게 봇 링크 전달 + 예정 발송 시각 안내

---

## 7. 알려진 리스크

| 리스크 | 영향 | 대응 |
| --- | --- | --- |
| 구글 시트 gviz CSV는 비공식 엔드포인트 | 사양 변경 시 전체 시트 소스 중단 | P1-1의 Apps Script 경로를 대체 수단으로 확보 |
| 구글 뉴스 RSS 응답 포맷 변경 | 브리핑 잡 중단 | `parse_feed` 단위 테스트로 조기 감지, 네이버 API 소스(P1-2)로 이중화 |
| Actions 스케줄 지연/누락 | 보고 미발송 | tick 윈도우로 완화. 완전 누락 대비 P1-3의 `/run` 수동 트리거 |
| 토큰 사용량 급증 | 구독 원가 역전 | P0-1의 계측 + `source.limit`/`max_input_chars` 상한 |
| 고객 데이터 외부 전송 | 계약·법적 문제 | 납품 전 서면 동의. 개인정보 열은 수집에서 제외 |
| 프롬프트 변경으로 출력 품질 저하 | 고객 불만 | P2-2의 A/B 기록으로 되돌릴 근거 확보 |

---

## 8. 참고 링크

- 저장소: https://github.com/NAMSOO-KIM/auto-cpna
- 브랜치: `claude/ai-bot-automation-monetization-vimz44`
- 기술 문서: `docs/botkit.md`
- 수익화 플레이북: `docs/monetization-playbook.md`
- 잡 템플릿: `config/jobs/_TEMPLATE.yaml`
