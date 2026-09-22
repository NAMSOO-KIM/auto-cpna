# botkit - 고객사 업무 자동화 봇 보일러플레이트

구글시트/RSS/JSON API에서 데이터를 모아 → Claude로 정리하고 → 텔레그램(또는 슬랙)으로
보내는 봇을, **코드 수정 없이 YAML 한 장으로** 찍어내기 위한 패키지다.

한 건 납품에서 손대는 파일은 원칙적으로 `config/jobs/<고객사>.yaml` 하나뿐이다.
파이썬 파일을 열어야 한다면 그건 딜럭스 이상 작업이거나, 이 보일러플레이트에
기능을 하나 추가해야 한다는 신호다.

```
config/jobs/*.yaml   ─┐
                      ├─ botkit run --due-now  ─→ 수집 → Claude → 텔레그램
GitHub Actions(매시) ─┘        (src/botkit)
```

---

## 1. 5분 만에 돌려보기

```bash
pip install -e ".[dev]"

cp .env.example .env            # ANTHROPIC_API_KEY, TELEGRAM_* 채우기
cp config/jobs/_TEMPLATE.yaml config/jobs/acme.yaml

botkit validate                 # 스키마 + 환경변수 점검
botkit test-telegram --job acme # 고객 채팅방 연결 확인
botkit run --job acme --dry-run # 발송 없이 결과만 확인
botkit run --job acme           # 실제 발송
```

| 명령 | 언제 쓰나 |
| --- | --- |
| `botkit list` | 등록된 잡과 스케줄 확인 |
| `botkit validate` | 납품 전 최종 점검 (환경변수 누락 시 exit 1) |
| `botkit due` | "지금 실행 대상인 잡" 확인 (스케줄 디버깅) |
| `botkit run --job X [--dry-run]` | 잡 1건 즉시 실행 |
| `botkit run --due-now --state-file .botkit/state.json` | 스케줄러 진입점 (Actions가 호출) |
| `botkit test-telegram --job X` | 고객 채팅방 연결 확인 |
| `botkit report --month YYYY-MM [--history-dir PATH]` | UTC 회차 월별 실행·토큰·추정 비용 조회 |

## 2. 잡 YAML 구조

```yaml
title: "고객사명 - 업무 요약 봇"     # 고객이 보는 이름
enabled: true

schedule:                          # 고객사 현지 시각 기준
  timezone: "Asia/Seoul"
  times: ["08:00", "18:00"]
  weekdays: [mon, tue, wed, thu, fri]   # 생략 = 매일

source: { ... }                    # 아래 4종 중 하나
prompt: { system, user_template, model, max_tokens, effort }
sinks: [ { type: telegram | webhook } ]

skip_when_empty: true              # 수집 0건이면 API 호출 없이 건너뜀
max_input_chars: 40000             # 프롬프트에 넣을 수집 데이터 상한
history:
  enabled: true
  directory: ".botkit/history"
  pricing_file: "config/pricing.yaml"
```

### 실행 이력 YAML 옵션 (P0-1)

| 키 | 기본값 | 동작 |
| --- | --- | --- |
| `history.enabled` | `true` | 성공·실패·빈 입력·중복 회차·dry-run 이력 기록. `false`면 이력/비용 집계를 끔 |
| `history.directory` | `.botkit/history` | 월별 JSONL 디렉터리. 상대 경로는 실행 작업 폴더 기준 |
| `history.pricing_file` | `config/pricing.yaml` | 모델별 USD/백만 토큰 단가표. 고객별 Python 수정 불필요 |

Actions에서 `history.directory`는 반드시 `.botkit/` 내부여야 한다. 그 밖의 경로는
백업 누락을 막기 위해 API 호출 전에 실패한다. 로컬에서는 다른 경로도 사용할 수 있다.
단가표의 모델 누락/잘못된 단가는 `botkit validate`와 실행 사전 점검에서 실패한다.
비활성 예시 잡 3개는 기존처럼 유지되며, `--job` 수동 실행은 비활성 잡도 의도적으로 실행한다.

키를 하나라도 틀리게 적으면 로드 단계에서 실패한다(`extra="forbid"`). `sytem:`처럼
한 글자 틀린 키가 조용히 무시되면 "프롬프트를 고쳤는데 결과가 그대로"인 상황이
벌어지기 때문에 일부러 좁게 잡았다.

### 소스 4종

| type | 용도 | 핵심 옵션 |
| --- | --- | --- |
| `google_sheet` | 시트에 쌓인 문의/발주/재고 | `sheet_id`, `sheet_name`/`gid`, `where_empty`, `where_equals`, `limit` |
| `rss` | 뉴스·블로그 키워드 모니터링 | `feeds`, `since_hours`, `limit`, `summary_chars` |
| `http_json` | 고객사 어드민 / Apps Script 웹앱 | `url`, `headers`(`env:NAME` 표기), `items_path`, `fields` |
| `static` | YAML에 직접 적은 고정 목록 | `rows` |

- **google_sheet**는 OAuth 없이 gviz CSV 엔드포인트만 쓴다. 시트 공유를
  "링크가 있는 모든 사용자 - 뷰어"로 바꿔야 읽힌다(아니면 로그인 HTML이 와서
  실패한다 — 납품 직후 1순위 장애 원인). 각 행에는 시트 실제 행 번호가 `_row`로
  붙어서, 프롬프트에서 "12행에 답변을 채워주세요"처럼 위치를 지목할 수 있다.
- **rss**는 구글 뉴스 검색 RSS(`https://news.google.com/rss/search?q=<URL인코딩 키워드>&hl=ko&gl=KR&ceid=KR:ko`)와
  잘 맞는다. 피드 하나가 죽어도 나머지로 보고는 나가고, 전부 실패할 때만 에러가 된다.
- **http_json**의 헤더 값에 `env:CLIENT_ADMIN_TOKEN`처럼 쓰면 실행 시 환경변수로
  치환된다. 고객사 API 키를 YAML에 평문으로 남기지 않기 위한 표기다.

### 프롬프트 (납품 작업의 90%)

`user_template`에는 `{rows}`가 반드시 있어야 한다. 그 외에 `{date}`, `{time}`,
`{row_count}`, `{job_title}`을 쓸 수 있고, **모르는 중괄호는 그대로 둔다**.
고객 프롬프트에 JSON 예시가 섞여 들어와도 `KeyError`로 새벽 스케줄이 죽지 않는다.

모델 기본값은 `claude-opus-5`다. 매일 도는 잡의 비용을 낮추려면 `effort: low`를
먼저 시도하고(같은 모델, 더 적은 토큰), 그래도 부족하면 그때 모델을 바꾼다.

### 싱크

```yaml
sinks:
  - type: telegram
    bot_token_env: "TELEGRAM_BOT_TOKEN"   # 값이 아니라 '환경변수 이름'
    chat_id_env: "TELEGRAM_CHAT_ID"
    parse_mode: "none"                    # 기본 평문
    header: "[{job_title}] {date}"
  - type: webhook
    url_env: "SLACK_WEBHOOK_URL"
    text_key: "text"
```

`parse_mode` 기본값이 `none`인 이유: LLM 본문에 섞인 `*`, `_`, `[` 가 텔레그램
마크다운 파서에 걸려 400으로 통째로 반송되는 사고가 가장 흔하다. 굳이 서식을
켜더라도 파싱 실패 시 평문으로 한 번 더 시도하도록 되어 있다 — 서식 때문에
보고가 아예 안 가는 것보다 낫다.

4096자 상한도 자동으로 처리한다(문단 → 줄 → 강제 절단 순으로 경계를 찾아 분할).

## 3. 스케줄이 동작하는 방식

GitHub Actions의 cron은 UTC 고정이고, 실행이 수 분~십수 분 밀리는 일이 흔하다.
그래서 워크플로는 **매시 정각에 깨우기만** 하고, 어떤 잡을 보낼지는 고객사
타임존 기준으로 botkit이 판단한다.

- `--tick-minutes 60`: "직전 60분 안에 예정 시각이 있었는가"로 판정한다.
  08:00 예정 잡은 08:50에 깨어난 실행에서도 실행된다.
- `--state-file`: 마지막으로 실행한 **회차(예정 시각)** 를 기록한다. 한 시간 안에
  두 번 깨어나도 같은 "08:00분"을 두 번 보내지 않는다. Actions에서는
  `actions/cache`로 `.botkit/`(상태와 실행 장부)를 주고받는다. 캐시가 유실되면 최악의 경우 1회
  중복 발송이고, 동작 자체는 막지 않는다.
- 실패한 잡은 상태에 기록되지 않는다. 같은 예정 회차가 다음 실행의 tick 윈도우에도
  들어 있을 때 재시도한다. 매시 실행에서 이전 회차가 이미 윈도우 밖으로 밀렸으면
  그 회차가 자동으로 재실행되지는 않는다. `--job`은 수동 재실행 경로다.
- 잡 하나가 실패해도 나머지는 계속 나간다. 고객사 A의 시트 공유 설정이 풀렸다고
  고객사 B의 아침 보고가 같이 빠지면 그게 더 큰 사고다.

> `--tick-minutes`는 워크플로 cron 간격과 **같은 값**이어야 한다. cron을
> `0 */3 * * *`로 줄였다면 `--tick-minutes 180`으로 함께 바꾼다. 안 그러면
> 그 사이에 예정된 회차가 통째로 누락된다.

## 4. GitHub Actions 배포

`.github/workflows/botkit.yml`이 매시 정각에 `botkit run --due-now`를 호출한다.
수동 실행(`workflow_dispatch`)에서는 잡 이름과 dry-run 여부를 고를 수 있어,
고객 앞에서 시연하거나 장애 시 재발송할 때 쓴다.

등록할 Secrets (Settings → Secrets and variables → Actions):

| 이름 | 값 |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude API 키 |
| `TELEGRAM_BOT_TOKEN` | @BotFather `/newbot` 발급 토큰 |
| `TELEGRAM_CHAT_ID` | 고객 채팅 ID (개인: @userinfobot / 그룹: `-100`으로 시작) |
| `OPS_TELEGRAM_CHAT_ID` | **운영자 전용** 실패 알림 채널 (고객 채팅방과 반드시 분리) |
| `SLACK_WEBHOOK_URL`, `CLIENT_ADMIN_TOKEN` | 잡 YAML에서 참조할 때만 |

실행이 실패하면 운영자 채널로 실패 로그 링크가 날아간다. 고객이 "오늘 보고
안 왔는데요?"라고 먼저 알려주는 상황을 막기 위한 최소 장치다.

추가 Secret은 필요 없다. `BOTKIT_JOB`은 Actions 수동 입력을 쉘에 안전하게 전달하는
일반 환경변수이며 `.env.example`에도 명시한다. 로컬에서는 계속 `--job`을 사용한다.

### 이력 보존과 복원

- 성공/실패/수동/dry-run 모두 `.botkit/` 캐시 저장을 시도한다. dry-run은
  중복 방지 상태를 갱신하지 않지만 **Claude 비용이 발생하므로 장부는 저장**한다.
- 캐시 키에 run ID와 run attempt를 넣어 워크플로 재실행도 새 기록을 보관한다.
- 각 실행의 `botkit-ledger-<run_id>-<attempt>` artifact에 `.botkit/` 누적 스냅샷을
  별도로 보관한다. 요청 보존 기간은 90일이며 저장소/조직 정책이 우선한다.
- 캐시는 영구 저장소가 아니다. 캐시 유실/퇴출, artifact 만료, 강제 취소, 러너 중단으로
  기록이 빠질 수 있다. 월별 정산 때 artifact를 내려받아 접근 제한된 운영자 보관소에 백업한다.
- 복원: 해당 브랜치의 정상 artifact ZIP을 다운로드 → 압축 내부의 월별 JSONL을
  로컬 `.botkit/history/`에 복원 → `botkit report --month YYYY-MM` 실행.
  복원할 파일이 기존 파일을 덮어쓰는 경우 먼저 기존 파일을 따로 백업한다.
- 캐시가 유실된 구간이 있다면 여러 artifact의 **같은 월 JSONL 줄을 합친다**.
  report는 동일한 `history_id`/내용을 중복 집계하지 않는다. 같은 ID의 내용이 다르면 실패한다.
  최신 artifact 하나가 전체 월 이력을 포함한다고 가정하지 않는다.
- 예약 발송 상태의 운영 복원은 고객 연결/Production 변경이므로 사용자 승인 후 진행한다.
  비용 분석용 로컬 복원에는 `state.json`을 덮어쓸 필요가 없다.
- 로컬 동시 실행은 지원하지 않는다. 같은 장부를 쓰는 프로세스는 순차 실행한다.
- **발송이 끝난 뒤의 장부 실패는 실행 상태를 뒤집지 않는다.** 뒤집으면 중복 방지
  상태가 기록되지 않아 다음 tick에 같은 회차가 고객에게 다시 간다. 이미 도착한
  메시지는 되돌릴 수 없으므로, 장부 누락은 `ledger_error`와 종료 코드 1(운영자
  알림)로만 올린다. 반대로 발송 전 단계의 장부 실패는 실행을 중단시킨다 -
  기록 없이 유료 호출이 나가는 경로는 없다.
  Actions는 기존 concurrency 직렬화를 유지한다.

## 5. 고객사 리포지터리로 떼어내기

botkit은 `autocpna`(쿠팡/네이버 제휴 파이프라인)를 import하지 않는다. 고객사
리포지터리는 아래 공통 파일과 고객 YAML을 함께 준비한다.

```
src/botkit/                      # 코드
config/jobs/<고객사>.yaml         # 그 고객의 잡만
config/pricing.yaml             # 공통 단가표 (기본 이력 기능에서 필요)
.github/workflows/botkit.yml     # 스케줄러
```

여기에 botkit CLI entry point와 다섯 의존성을 선언한 패키지 설정 및 `.env.example`이
필요하다. 원본 `pyproject.toml`에는 별도 상품 autocpna용 DB 의존성도 있으므로,
고객용 최소 패키지에서는 botkit에 필요한 설정만 사용한다. 공통 파일은 보일러플레이트에
포함하고 고객 주문마다 새로 작성하는 파일은 `config/jobs/<고객사>.yaml` 한 장이다.

필요한 패키지는 `anthropic`, `httpx`, `pydantic`, `pyyaml`, `click` 다섯 개뿐이다
(DB·SQLAlchemy는 autocpna 쪽 의존성이라 botkit에는 필요 없다).

## 6. 자주 나는 오류

| 증상 | 원인과 조치 |
| --- | --- |
| `구글 시트를 CSV로 읽지 못했습니다` | 시트 공유가 비공개. "링크가 있는 모든 사용자 - 뷰어"로 변경 |
| `텔레그램 발송 실패 ... chat not found` | 봇을 채팅방에 초대하지 않았거나 chat_id 오타. 그룹 ID는 `-100` 시작 |
| `환경변수 ...이(가) 비어 있습니다` | Actions Secrets 미등록. `botkit validate`로 사전 확인 |
| `응답이 max_tokens에서 잘렸습니다` | `prompt.max_tokens`를 올리거나 `source.limit`을 줄인다 (잘린 보고는 발송하지 않는다) |
| 보고가 두 번 왔다 | 상태 캐시 유실. 워크플로의 cache 스텝과 `--state-file` 경로 확인 |
| 보고가 안 왔다 | `botkit due`로 판정 확인 → cron 간격과 `--tick-minutes`가 맞는지 확인 |
| 단가표 오류 / 모델 단가 없음 | `history.pricing_file`, `prompt.model`, `config/pricing.yaml` 확인 |
| 이력 저장 실패(발송 전) | 실행이 중단된다. 디스크·권한 확인 후 재실행 (유료 호출 전이라 비용 없음) |
| 이력 저장 실패(발송 후) | 발송은 완료된 상태다. **재실행하지 말 것** - 상태는 기록돼 중복 발송은 없고, 그 회차의 장부만 비어 있다. 종료 코드 1로 운영자 알림이 뜬다 |
| report 이력 검증 실패 | 표시된 월/줄 번호를 확인하고 artifact 원본과 대조. 오류 줄을 삭제해 합계를 맞추지 않음 |

## 7. 월별 비용 계측

`botkit report --month 2026-09`는 잡별 `runs`, `ok`, `skipped`, `failed`, `dry-run`,
`input_tokens`, `output_tokens`, `USD`, `unknown`을 TSV 표로 출력한다.
다른 이력 디렉터리는 `--history-dir .botkit/acme/history`로 선택한다.
`runs`는 기록된 시도/중복 회차 확인 횟수이며 `skipped`도 포함한다. 비활성/예정 외 잡은 기록하지 않는다.
이력이 없는 경우 0원 보고서를 만들지 않고, 경로와 백업 복원을 확인하라는 안내를 출력한다.

각 줄은 다음 필드를 갖는다.

| 필드 | 의미 |
| --- | --- |
| `schema_version`, `history_id` | 형식 버전 1, 실행별 고유 ID (백업 중복 제거) |
| `job_name`, `model` | 잡 이름, 요청 모델 |
| `fire_at`, `finished_at` | 예정 회차와 실제 종료 시각. 수동 실행의 회차는 시작 시각 |
| `status`, `skip_reason` | ok/skipped/failed/dry-run, empty/already_ran |
| `row_count` | 성공적으로 수집된 행 수 |
| `input_tokens`, `output_tokens` | Claude 응답 usage 값. 확인 불가능한 값은 null |
| `estimated_cost_usd`, `pricing` | 실행 당시 단가로 계산한 비용과 단가 스냅샷. Decimal을 JSON 문자열로 저장 |
| `message_ids` | Telegram에서 성공 응답으로 확인한 ID 목록. 실패 전 청크도 포함 |
| `error` | 오류 단계와 예외 종류. 응답/예외 원문, 토큰, 채팅 ID는 기록하지 않음 |
| `cache_tokens_seen` | 캐시 과금이 섞여 단가 계산 범위를 벗어난 실행. 이때 `estimated_cost_usd`는 null |

파일명은 **fire_at을 UTC로 변환한 월**을 사용한다. 예: KST 10월 1일 08:00 회차는
UTC 9월 30일 23:00이므로 `2026-09.jsonl`에 기록된다. 종료가 다음 달이어도 회차 월에 남는다.

비용은 `(input_tokens × 입력 단가 + output_tokens × 출력 단가) / 1,000,000`으로 계산한다.
단가는 [Anthropic 공식 가격표](https://platform.claude.com/docs/en/about-claude/pricing)를
2026-09-22에 확인해 공통 YAML에 넣었다. 모델 단가가 바뀌어도 과거 기록을 재계산하지 않는다.
도구/배치/캐시/지역 가산·할인·세금·환율을 포함하지 않는 일반 직접 Messages API 추정치다.
현재 요청에는 캐시/도구 기능을 사용하지 않는다. 예상 밖 캐시 usage가 반환되면
비용을 임의 계산하지 않고 `cache_tokens_seen: true` + 비용 null로 표시하되,
**발송은 그대로 진행한다** - 회계 정확도를 위해 전 고객 보고를 동시에 멈추는 것은
거래가 거꾸로다. report의 `unknown` 건수로 청구서와 대조한다.

잘림/거절·Telegram 실패도 이미 받은 usage는 기록한다. timeout처럼 응답을 받지 못한
실행의 비용은 `null`이며 report의 `unknown`에 표시하고 USD 합계에서 제외한다.
입력 단계 실패/빈 입력처럼 API를 호출하지 않은 실행은 0원이다.
**unknown이 있거나 실행/백업 누락이 있으면 USD 합계는 완전한 월 원가가 아니다.**
SDK 내부 재시도의 응답 없는 시도도 완전히 계측할 수 없으므로 API 청구서와 대조한다.

P0-1은 메타데이터 장부다. 개인정보 최소화를 위해 입력/생성 본문을 보관하지 않으며
과거 보고 본문 재열람·전달 기능(P0-3)은 아직 없다. ID는 Telegram 채팅 내에서만 고유하며
여러 채널의 ID를 해석할 때는 해당 실행의 잡 설정도 함께 확인한다.
부분 발송 뒤 실패한 잡은 기존 원칙대로 성공 상태에 기록하지 않아 재실행 시 일부가
중복될 수 있다. 자동 재실행 전에 채널을 확인하며 exactly-once를 보장하지 않는다.
