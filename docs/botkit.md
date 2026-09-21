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
```

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
  `actions/cache`로 이 파일만 주고받는다. 캐시가 유실되면 최악의 경우 1회
  중복 발송이고, 동작 자체는 막지 않는다.
- 실패한 잡은 상태에 기록되지 않으므로 **다음 tick에서 자동 재시도**된다.
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

## 5. 고객사 리포지터리로 떼어내기

botkit은 `autocpna`(쿠팡/네이버 제휴 파이프라인)를 import하지 않는다. 고객사
리포지터리에는 아래 세 덩어리만 복사하면 그대로 돈다.

```
src/botkit/                      # 코드
config/jobs/<고객사>.yaml         # 그 고객의 잡만
.github/workflows/botkit.yml     # 스케줄러
```

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
