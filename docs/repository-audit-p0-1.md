# Repository Audit 및 P0-1 구현 승인안

작성일: 2026-09-22. 아래는 구현 전 승인안의 보존본이다.
사용자의 “진행해” 승인 후 저장소에 함께 보관했다. 당시 승인 대기/검증 상태는
기준선 기록이며, 최종 구현·검증 상태는 [P0-1 릴리스 기록](releases/p0-1.md)을 따른다.

## 1. 조사 기준과 범위

- 저장소: `https://github.com/NAMSOO-KIM/auto-cpna`
- 브랜치: `claude/ai-bot-automation-monetization-vimz44`
- 실제 HEAD: `0cdaf83` — 사용자 지정 기준과 일치, 작업 트리 변경 없음.
- 상품 지시서 → `docs/botkit.md` → `src/botkit/` 전 파일을 읽었다.
- 이후 두 Actions, 예시 YAML/템플릿, 환경변수 예시, 전체 테스트 구조와 botkit 테스트 7개 파일, 수익화 문서를 조사했다.
- 지시서 표의 `f170ba8`은 이전 구현 기준이다. 실제 작업 기준은 사용자가 지정한 `0cdaf83`이다.
- 신규 구현은 우선 P0-1 한 기능만 진행한다. P0-2 이후 작업은 이번 승인안에 포함하지 않는다.

## 2. 현재 구조

```text
src/botkit/              고객 납품용 독립 실행기
  jobspec.py            strict YAML 모델 및 로딩
  cli.py                list / validate / due / run / test-telegram
  runner.py             수집 → 생성 → 발송, 잡 단위 실패 격리
  llm.py                Claude 호출, 프롬프트 치환 및 응답 검증
  schedule.py           타임존, 요일, tick 윈도우
  state.py              마지막 실행 회차 JSON
  settings.py           환경변수 및 .env 로더
  sources/              Google Sheet CSV / RSS·Atom / HTTP JSON / static
  sinks/                Telegram / outbound webhook
config/jobs/            템플릿 1개 + 비활성 예시 3개
.github/workflows/      botkit 스케줄러 + 전체 CI
tests/                  botkit 회귀 테스트 + 기존 제휴 파이프라인 테스트
src/autocpna/           별도 제휴 콘텐츠 상품 (이번 구현 수정 대상 아님)
dashboard/              별도 상품 Streamlit 화면
docs/                   botkit 기술 문서, 수익화·납품 플레이북
```

`botkit`의 외부 직접 import는 anthropic/httpx/pydantic/yaml/click으로 제한되어 있다.
`autocpna`, SQLAlchemy import는 없다. 기존 디렉터리 구조를 유지한다.

## 3. 기능별 재사용 판정

| 조사 항목 | 분류 | 확인 결과 / 이번 작업 |
| --- | --- | --- |
| LLM Client / Claude API | MODIFY | `llm.generate()`가 문자열만 반환. usage를 동반한 dataclass로 확장 |
| OpenAI API | UNNECESSARY | autocpna의 이미지 생성에 존재. botkit에 추가하지 않음 |
| Prompt 관리 | REUSE | YAML system/user_template/model/effort, 안전한 정규식 치환 |
| Telegram Bot / Notification | MODIFY | 분할·재시도·운영자 알림 재사용. 메시지 ID와 부분 성공을 실행 결과까지 전달 |
| GitHub Actions | MODIFY | cron·수동 실행·직렬화·실패 알림 유지. 이력 보존 추가 |
| Scheduler / Cron | REUSE | 타임존과 tick 판정, 매시 정각 cron |
| Webhook 송신 | REUSE | Slack 등 범용 POST 기존 구현 |
| Webhook 수신 / 인바운드 명령 | MISSING | P1-3 범위, 이번 P0-1에서는 추가하지 않음 |
| Supabase / Database | UNNECESSARY | autocpna에 SQLAlchemy/SQLite/Postgres, dashboard에 Supabase 연결 안내. botkit에 DB 도입 금지 |
| Authentication | REUSE | 외부 API 환경변수 인증 재사용. 사용자 로그인 화면은 이번 상품에 불필요 |
| Crawler / 데이터 수집 | REUSE | 시트/RSS/JSON/static. 네이버 검색은 P1-2 미구현 |
| API | REUSE | Claude·Telegram·고객 JSON API 호출. 새 서버 불필요 |
| Logging | MODIFY | CLI 결과·실패 사유는 존재. 지속 실행 이력/비용 집계는 없음 |
| Error Handling | MODIFY | 12개 방어 유지. 이력에 원문 예외를 저장하지 않도록 안전한 오류 분류 보강 |
| Deployment | MODIFY | 기존 Actions를 확장. 신규 배포 플랫폼 불필요 |
| Tests | MODIFY | 기존 회귀 테스트 유지, P0-1 성공·실패·월별 집계 테스트 추가 |
| 발송 이력 / 모델 단가 / 월별 report | MISSING | P0-1 신규 구현 대상 |
| 승인 모드 / 시트 되쓰기 / 온보딩 CLI | MISSING | 각각 후속 P0-3/P1/P2 범위 |

## 4. 12개 방어 확인

| 방어 | 확인 위치 | 유지 방법 |
| --- | --- | --- |
| extra=forbid | jobspec.Strict | 신규 history 옵션에도 적용 |
| 정규식 플레이스홀더 | llm.render | 변경 불필요 |
| max_tokens/refusal 차단 | llm.extract_text | 발송 차단 유지, 응답 usage만 실패 이력에 보존 |
| thinking 건너뛰기 | llm.extract_text | 기존 text 필터 유지 |
| parse_mode none + 400 평문 재시도 | sinks/telegram.send | 재시도 흐름 유지 |
| 장문 분할 | sinks/telegram.split_message | 문단/줄/강제 절단 유지 |
| 시트 필터 열 검증 | sources/google_sheet.check_columns | 변경 불필요 |
| 잡 단위 실패 격리 | runner.run_due | 이력 실패도 잡 경계에서 표시 |
| 실패 잡 상태 미기록 | runner.run_due | 성공/빈 입력 skipped 상태 기록 규칙 유지 |
| tick 윈도우 | schedule.due_at | 변경 불필요 |
| 환경변수 우선 | settings.load_env_file | 변경 불필요 |
| 운영자 전용 실패 알림 | botkit.yml | 고객 채널로 에러를 보내지 않음 |

## 5. P0-1 변경 계획

1. `llm.py`: text, input_tokens, output_tokens를 가진 결과 dataclass 도입.
   응답 검증 실패에도 반환된 usage를 잃지 않도록 오류에 계측 정보를 연결한다.
   API 응답이 없는 timeout 등의 사용량은 0으로 단정하지 않고 미확인으로 구분한다.
2. `jobspec.py`: 고객 YAML에 `history.enabled`, `history.directory`,
   `history.pricing_file` 옵션을 추가한다. 기본 경로는 `.botkit/history`, `config/pricing.yaml`.
   플랫폼 공통 단가 파일을 제공하므로 고객 납품 시 추가 작성 파일은 YAML 한 장을 유지한다.
3. 신규 `history.py` / `pricing.py`: 표준 라이브러리와 기존 pydantic/PyYAML만 사용한다.
   월별 JSONL append, 엄격한 가격 검증, 월별 잡 집계를 분리한다.
   단가는 USD/백만 토큰 기준으로 YAML에 두고 코드에 넣지 않는다.
   미등록 모델·잘못된 가격은 유료 호출 전에 명확히 실패시킨다.
4. `runner.py`: 실행 시도마다 기록을 남긴다. 필수 필드는
   job_name/fire_at/finished_at/status/row_count/input_tokens/output_tokens/
   estimated_cost_usd/message_ids/error이다. 식별·감사를 위해 실행 ID와 모델/적용 단가도 보존한다.
   스케줄 실행의 fire_at은 실제 시작 시각이 아니라 예정 회차이며,
   수동 실행은 시작 시각을 사용한다. 파일 월 구분 기준을 UTC로 문서화한다.
   dry-run도 Claude를 호출하므로 비용 집계에 포함하되 상태를 구별한다.
5. `sinks/__init__.py`, `sinks/telegram.py`: 성공 ID와 일부 청크/싱크만 성공한 결과를 보존한다.
   실패를 성공으로 바꾸거나 자동 재발송 정책을 확대하지 않는다.
6. `cli.py`: `botkit report --month YYYY-MM` 및 이력 경로 옵션을 추가한다.
   잡별 실행 횟수, 상태, 입출력 토큰, USD 추정 비용, 미확인 사용량 건수를 표시한다.
   읽을 수 없는/깨진 이력을 조용히 누락시키지 않는다.
7. `.github/workflows/botkit.yml`: 수동·dry-run·실패 실행의 이력도 보존하도록 저장 조건을 수정한다.
   캐시와 별도로 실행별 이력 artifact를 남기는 방식을 적용하고 재실행 키 충돌을 피한다.
   기존 중복 방지 상태와 스케줄 직렬화는 유지한다. 보존 실패도 드러나야 한다.
8. 기술 문서 옵션 표·템플릿·수익화 문서·테스트를 함께 갱신한다.
   신규 환경변수는 필요 없도록 YAML을 사용한다. 필요해지면 .env.example과 Actions env에 동시에 반영한다.

## 6. 테스트 계획과 기존 테스트 변경 범위

- 기존 전체 테스트와 ruff를 먼저 실행해 기준선을 기록한다.
- 성공/빈 입력/disabled/중복 회차/dry-run/수동 실행/스케줄 실행의 이력을 검증한다.
- LLM API 실패·timeout·network 오류·거절·잘림, Telegram 실패·부분 발송을 검증한다.
- 발송 실패 후에도 이미 발생한 토큰 비용이 남는지 검증한다.
- JSONL 쓰기 실패·손상·월 경계·잘못된 월·미등록 모델·잘못된 단가를 검증한다.
- 오류에 토큰/인증 헤더/본문이 들어가지 않는지 검증한다.
- 각 신규 테스트 docstring에 사고 방지 목적을 적는다.
- `test_botkit_llm.py`의 문자열 반환 assertion 및 `test_botkit_runner.py`의 문자열 mock은
  지시서가 요구한 반환 타입 변경 때문에 갱신이 필요하다. 새로운 dataclass/usage fixture로
  바꾸되 원래 본문·발송·격리·중복 방지 assertion을 삭제하거나 약화하지 않는다.
- 모델 단가의 실제 최신 값은 구현 시 공식 자료로 확인한다. 현재 문서의 값을 검증 없이 확정하지 않는다.

## 7. 발견한 제약 및 후속 항목

- `deliver()`는 현재 Telegram ID를 요약 문자열로 바꿔 버린다. 전체/부분 성공 증거 전달이 필요하다.
- 현재 캐시는 `.botkit` 전체를 복원하지만 저장은 스케줄의 non-dry-run만 수행한다.
- Actions 캐시는 영구 장부가 아니다. artifact 보존 기간과 다운로드·백업 절차를 명시해야 한다.
- 부분 발송 뒤 실패한 잡은 상태 미기록 원칙 때문에 재시도 때 이미 보낸 부분이 중복될 수 있다.
  이번 작업은 이를 숨기지 않고 기록한다. exactly-once를 주장하지 않는다.
- 지시서 P0-1의 필수 필드에는 보고 본문이 없다. 메타데이터 기록만으로 과거 보고 본문 재열람은 불가능하다.
  이번에는 원문 입력/출력을 기본 저장하지 않고, 원문 보관·전달은 P0-3 승인 기능에서 명시적으로 설계한다.
- 현재 Google Sheet 소스에는 fields 옵션이 없다. where_equals는 행 필터이며 개인정보 열 제거 기능이 아니다.
  수익화 문서의 열 제한 설명은 실제 구현과 차이가 있어 후속 문서 정정 대상이다.
- 시트 되쓰기는 현재 구현되지 않았다. 판매 문구에서 구현 완료로 표현하면 안 된다.
- 현재 체크아웃의 대표적인 API 키/Telegram 토큰 패턴 검사에는 일치가 없었다.
  전체 Git 이력에 대한 시크릿 감사는 수행하지 않았다.
- HTTP 오류/응답 본문을 CLI에 그대로 출력할 수 있는 기존 경로가 있다. P0-1에서는
  이를 이력에 복제하지 않고 안전한 오류 종류·단계 중심으로 기록한다.
- 전체 pyproject는 autocpna용 DB 의존성도 설치한다. botkit의 직접 import 제한과 구분되며,
  고객용 최소 패키징은 후속 납품 준비에서 다룬다.

## 8. 승인 및 릴리스 경계

- 사용자의 “현재 구조와 변경 계획을 먼저 요약해서 보여주고, 내 확인을 받은 다음 코드를 고쳐” 지시에 따라 승인 대기.
- 승인 후 P0-1 기능을 테스트·문서와 함께 한 커밋으로 묶는다. 메시지는 비용 누락 방지의 이유를 설명한다.
- 푸시는 지정 브랜치에만 수행한다. PR은 요청 전 생성하지 않는다.
- Production 변경, 고객 시스템 연결, 고객 데이터 migration, 고객 최종 전달,
  유료 API 활성화, 크몽 게시 직전 CHANGELOG/TEST RESULT/DEPLOYMENT PLAN/KNOWN ISSUES/ROLLBACK PLAN을 보고하고 별도 승인 대기.
- 실제 LLM/Telegram 호출과 운영 워크플로 실행은 이번 조사에서 수행하지 않는다.

## 9. 기준선 검증 결과

| 검증 | 결과 |
| --- | --- |
| 가상환경 + pip install -e ".[dev]" | 성공 |
| pytest -q | 165 passed, 78 warnings, 3.50초 |
| botkit 관련 테스트 개수 | 68개 (전체 통과 결과에 포함) |
| botkit list | 예시 3개 정상 조회, 모두 disabled |
| ruff check . | 실패: 기존 코드 44개 오류, Ruff 0.16.8 |
| git status --short | 출력 없음, 저장소 변경 없음 |

로컬 런타임은 Windows Python 3.12.14이며 Actions의 Python 3.11 결과와 구분한다.
실제 GitHub CI는 이번 조사에서 실행하지 않았다.
78개 경고는 기존 autocpna/SQLAlchemy의 datetime.utcnow 관련 DeprecationWarning이다.

Ruff는 저장소 pyproject.toml을 설정으로 읽는 것을 확인했다. 오류는 import 정렬,
datetime 관련 규칙, unused noqa, 예외 처리 등의 항목이며 botkit 이외 기존 코드도 포함한다.
pyproject에는 ruff>=0.15.0 하한만 있고 lint.select는 명시되어 있지 않다.
버전별 기본 규칙 차이가 원인인지는 추가 확인이 필요하므로 확정하지 않는다.
승인 후 기존 기준 버전/규칙과 비교해 최소한의 호환성 조치를 정하고,
lint 통과만을 위해 autocpna를 일괄 수정하거나 규칙을 임의로 비활성화하지 않는다.
별도 도구 설정 변경이 필요하면 P0-1과 구분한 이유 중심 커밋으로 처리한다.
