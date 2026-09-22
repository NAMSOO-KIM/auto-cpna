"""원가/발송 증거가 성공 경로에서만 남으면 실제 운영 원가를 과소평가한다."""
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from click.testing import CliRunner

from botkit import history, llm, runner, sinks, state
from botkit.cli import cli
from botkit.jobspec import JobConfigError, parse_job
from botkit.pricing import PricingError, load_price
from botkit.sinks import DeliveryError, DeliveryResult, telegram

NOW = dt.datetime(2026, 9, 21, 23, 5, tzinfo=dt.timezone.utc)
PRICING = Path(__file__).resolve().parents[1] / "config" / "pricing.yaml"
BASE = {
    "title": "합성 데모", "schedule": {"times": ["08:00"]},
    "source": {"type": "static", "rows": [{"문의": "가상 배송 문의"}]},
    "prompt": {"system": "초안만", "user_template": "{rows}"},
    "sinks": [{"type": "telegram"}],
}


@pytest.fixture
def job(tmp_path, monkeypatch):
    """회귀 테스트가 실제 작업 폴더 장부나 네트워크를 건드리지 않게 한다."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "synthetic-chat")
    return parse_job("acme", {**BASE, "history": {"pricing_file": str(PRICING)}})


def client(text="합성 AI 초안", reason="end_turn", input_tokens=1000, output_tokens=200):
    message = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], stop_reason=reason,
        stop_details=SimpleNamespace(category="test"),
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )
    return SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: message))


def records(job):
    return history.read_month(job.history.directory, "2026-09")


@pytest.fixture
def delivery(monkeypatch):
    """실제 고객에게 보내지 않고 발송 증거를 반환한다."""
    calls = []

    def send(*args, **kwargs):
        calls.append(args)
        return DeliveryResult(["telegram: 2개 메시지 발송"], [11, 12])

    monkeypatch.setattr(runner, "deliver", send)
    return calls


def test_success_records_usage_price_ids_and_no_body(job, delivery):
    """메시지 ID가 버려지거나 단가 변경으로 과거 비용이 바뀌는 사고를 막는다."""
    result = runner.run_job(job, now=NOW, client=client())
    record, = records(job)
    assert record.status == result.status == "ok"
    assert (record.row_count, record.input_tokens, record.output_tokens) == (1, 1000, 200)
    assert record.estimated_cost_usd == Decimal("0.010")
    assert record.message_ids == [11, 12]
    assert record.history_id == result.history_id
    assert record.pricing.input_usd_per_million == 5
    assert record.fire_at == NOW and record.finished_at.utcoffset() is not None
    raw = history.month_path(job.history.directory, NOW).read_text(encoding="utf-8")
    for sensitive in ["synthetic-key", "synthetic-token", "synthetic-chat", "합성 AI 초안", "가상 배송 문의"]:
        assert sensitive not in raw


def test_dry_run_cost_is_counted_without_delivery_or_state(job, delivery, tmp_path):
    """미리보기에도 API 비용이 발생하므로 장부에서 빠지면 원가를 과소평가한다."""
    state_path = tmp_path / "state.json"
    result, = runner.run_due([job], now=NOW, dry_run=True, state_path=state_path, client=client())
    record, = records(job)
    assert result.status == record.status == "dry-run"
    assert record.fire_at.minute == 0
    assert record.estimated_cost_usd == Decimal("0.010")
    assert not delivery and not state_path.exists()


def test_empty_and_duplicate_are_zero_cost_skips(job, delivery, tmp_path, monkeypatch):
    """빈 입력과 중복 회차는 API를 호출하지 않으면서 이유를 구분해 기록해야 한다."""
    monkeypatch.setattr(runner, "fetch_rows", lambda source: [])
    monkeypatch.setattr(llm, "generate", lambda *a, **k: pytest.fail("LLM 호출 금지"))
    path = tmp_path / "state.json"
    runner.run_due([job], now=NOW, state_path=path)
    runner.run_due([job], now=NOW, state_path=path)
    first, second = records(job)
    assert first.skip_reason == "empty" and second.skip_reason == "already_ran"
    assert first.estimated_cost_usd == second.estimated_cost_usd == 0
    assert len({first.history_id, second.history_id}) == 2
    assert not delivery


def test_disabled_and_not_due_jobs_have_no_attempt(job, delivery):
    """스케줄러가 깨어난 횟수를 실행/비용 발생 횟수로 오인하지 않게 한다."""
    job.enabled = False
    assert runner.run_due([job], now=NOW) == []
    job.enabled = True
    assert runner.run_due([job], now=NOW + dt.timedelta(hours=2)) == []
    assert records(job) == [] and not delivery


@pytest.mark.parametrize("reason", ["max_tokens", "refusal"])
def test_rejected_output_retains_billed_usage(job, delivery, reason):
    """잘림/거절 발송 방어를 유지하면서 이미 소비한 토큰은 청구 장부에 남긴다."""
    with pytest.raises(llm.GenerationError):
        runner.run_job(job, now=NOW, client=client(reason=reason))
    record, = records(job)
    assert record.status == "failed" and record.error == "llm:GenerationError"
    assert record.input_tokens == 1000 and record.estimated_cost_usd == Decimal("0.010")
    assert not delivery


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout, RuntimeError])
def test_llm_failure_has_unknown_cost_and_safe_error(job, delivery, error_type):
    """네트워크 예외에 시크릿이 섞여도 장부에는 남지 않으며 모르는 비용은 0원이 아니다."""
    def fail(**kwargs):
        raise error_type("synthetic-key synthetic-chat 고객 개인정보")

    fake = SimpleNamespace(messages=SimpleNamespace(create=fail))
    with pytest.raises(error_type):
        runner.run_job(job, now=NOW, client=fake)
    record, = records(job)
    assert record.input_tokens is record.output_tokens is record.estimated_cost_usd is None
    assert record.error == f"llm:{error_type.__name__}"
    assert record.status == "failed" and not delivery
    assert history.summarize([record])[job.name].unknown_cost_runs == 1


def test_source_failure_is_zero_cost_and_next_job_still_runs(job, tmp_path, delivery, monkeypatch):
    """입력 실패 잡이 다른 고객 보고를 막거나 사용하지 않은 API 비용을 만들면 안 된다."""
    healthy = job.model_copy(update={"name": "healthy"})
    attempts = []

    def fetch(source):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("private source URL")
        return [{"safe": "data"}]

    monkeypatch.setattr(runner, "fetch_rows", fetch)
    path = tmp_path / "state.json"
    results = runner.run_due([job, healthy], now=NOW, state_path=path, client=client())
    assert [r.status for r in results] == ["failed", "ok"]
    failed, successful = records(job)
    assert failed.row_count == 0 and failed.estimated_cost_usd == 0
    assert failed.error == "source:ReadTimeout" and successful.status == "ok"
    assert set(state.load_state(path)) == {"healthy"}


def test_partial_delivery_keeps_ids_and_cost(job, monkeypatch):
    """한 채널 성공 후 다음 채널이 실패해도 앞 발송의 증거와 LLM 비용을 잃지 않는다."""
    job.sinks.append(parse_job("other", {**BASE, "sinks": [{"type": "webhook", "url_env": "HOOK"}]}).sinks[0])
    monkeypatch.setattr(telegram, "send", lambda *a, **k: [17, 18])
    monkeypatch.setattr(sinks.webhook, "send", lambda *a: (_ for _ in ()).throw(RuntimeError("private")))
    with pytest.raises(DeliveryError):
        runner.run_job(job, now=NOW, client=client())
    record, = records(job)
    assert record.message_ids == [17, 18] and record.estimated_cost_usd == Decimal("0.010")
    assert record.status == "failed"


def test_telegram_partial_chunk_failure_keeps_confirmed_ids(job, monkeypatch):
    """장문의 뒤 청크 timeout은 앞 청크 발송까지 취소한 것처럼 보이면 안 된다."""
    calls = []

    def post(*args):
        calls.append(1)
        if len(calls) > 1:
            raise httpx.ReadTimeout("https://api.telegram.org/botsynthetic-token/sendMessage")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 71}})

    monkeypatch.setattr(telegram, "_post", post)
    with pytest.raises(DeliveryError) as caught:
        runner.run_job(job, now=NOW, client=client(text="가" * 4000))
    assert "synthetic-token" not in str(caught.value.__cause__)
    assert records(job)[0].message_ids == [71]


def test_no_history_option_does_not_require_pricing(job, delivery):
    """고객 YAML 한 장으로 기록을 끌 수 있고 이때 단가 파일이 실행을 막지 않아야 한다."""
    job.history.enabled = False
    job.history.pricing_file = "does-not-exist.yaml"
    assert runner.run_job(job, now=NOW, client=client()).status == "ok"
    assert not Path(job.history.directory).exists()


@pytest.mark.parametrize("patch", [{"unknown": True}, {"directory": " "}, {"pricing_file": ""}])
def test_bad_history_config_is_rejected(patch):
    """새 옵션에도 오타/빈 경로를 조용히 무시하는 예외를 만들지 않는다."""
    with pytest.raises(JobConfigError):
        parse_job("bad", {**BASE, "history": patch})


def test_missing_model_fails_before_input_or_paid_call(job, monkeypatch):
    """단가 없는 모델을 비용 0원으로 기록한 채 운영하지 않도록 유료 호출 전에 막는다."""
    job.prompt.model = "unpriced-model"
    monkeypatch.setattr(runner, "fetch_rows", lambda source: pytest.fail("선검증 필요"))
    with pytest.raises(PricingError):
        runner.run_job(job, now=NOW)
    record, = records(job)
    assert record.error == "preflight:PricingError" and record.estimated_cost_usd == 0


@pytest.mark.parametrize("bad", ["-1", ".nan", ".inf", "secret-value"])
def test_invalid_pricing_is_not_silent_or_leaked(tmp_path, bad):
    """음수/비정상 단가와 잘못 붙여넣은 시크릿을 계산하거나 에러에 노출하지 않는다."""
    path = tmp_path / "pricing.yaml"
    path.write_text(f'source: test\nchecked_on: "2026-09-22"\nmodels:\n  x:\n    input_usd_per_million: {bad}\n    output_usd_per_million: 1\n')
    with pytest.raises(PricingError) as exc:
        load_price(path, "x")
    assert bad not in str(exc.value)


def test_history_preflight_failure_never_calls_llm(job, monkeypatch):
    """이력을 쓸 수 없다는 걸 알면서 유료 실행부터 진행하면 안 된다."""
    Path("occupied").write_text("file")
    job.history.directory = "occupied/child"
    monkeypatch.setattr(llm, "generate", lambda *a, **k: pytest.fail("호출 금지"))
    with pytest.raises(history.HistoryError, match="경로"):
        runner.run_job(job, now=NOW)


def test_disk_failure_after_delivery_is_visible_and_not_marked(job, delivery, monkeypatch, tmp_path):
    """발송 뒤 디스크가 실패해도 장부와 중복 방지가 성공했다고 거짓 보고하지 않는다."""
    def fail(*args):
        raise history.HistoryError("이력 저장 실패")

    monkeypatch.setattr(history, "append", fail)
    path = tmp_path / "state.json"
    result, = runner.run_due([job], now=NOW, state_path=path, client=client())
    assert result.failed and "이력 저장 실패" in result.reason
    assert state.load_state(path) == {} and len(delivery) == 1


def test_month_is_scheduled_utc_month_not_completion_month(job, delivery):
    """자정 지연 실행이 이전 회차 비용을 다음 달로 옮기면 월별 원가가 흔들린다."""
    fire_at = dt.datetime(2026, 9, 30, 23, 59, tzinfo=dt.timezone.utc)
    runner.run_job(job, now=fire_at + dt.timedelta(minutes=5), fire_at=fire_at, client=client())
    assert records(job)[0].fire_at == fire_at
    assert history.read_month(job.history.directory, "2026-10") == []


@pytest.mark.parametrize("month", ["2026-13", "2026-9", "../../etc", "0000-01"])
def test_report_rejects_bad_month(tmp_path, month):
    """잘못된 기간이나 경로 이동 입력을 빈 보고서로 숨기면 안 된다."""
    result = CliRunner().invoke(cli, ["report", "--month", month, "--history-dir", str(tmp_path)])
    assert result.exit_code != 0 and "YYYY-MM" in result.output


def test_corrupt_history_is_reported_without_raw_line(job, delivery):
    """손상된 마지막 줄을 버리면 원가가 실제보다 줄어들고 원문 노출도 발생한다."""
    runner.run_job(job, now=NOW, client=client())
    path = history.month_path(job.history.directory, NOW)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("{private-personal-data\n")
    result = CliRunner().invoke(cli, ["report", "--month", "2026-09"])
    assert result.exit_code == 1 and ":2" in result.output
    assert "private-personal-data" not in result.output


def test_report_aggregates_stored_cost_and_deduplicates_backups(job, delivery):
    """여러 artifact를 합치거나 나중에 단가가 바뀌어도 과거 실행 원가는 동일해야 한다."""
    runner.run_job(job, now=NOW, client=client())
    runner.run_job(job, now=NOW, dry_run=True, client=client())
    path = history.month_path(job.history.directory, NOW)
    first = path.read_text(encoding="utf-8").splitlines()[0]
    with path.open("a", encoding="utf-8") as stream:
        stream.write(first + "\n")
    result = CliRunner().invoke(cli, ["report", "--month", "2026-09"])
    assert result.exit_code == 0
    assert "acme\t2\t1\t0\t0\t1\t2000\t400\t0.02000000\t0" in result.output
    assert len(records(job)) == 2


def test_history_record_is_strict(job, delivery):
    """손으로 수정된 장부의 잘못된 숫자를 보고서에서 자동 보정하면 안 된다."""
    runner.run_job(job, now=NOW, client=client())
    path = history.month_path(job.history.directory, NOW)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["input_tokens"] = -1
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(history.HistoryError):
        records(job)


@pytest.mark.parametrize("tokens", [None, -1, True, "1000"])
def test_invalid_usage_blocks_delivery_and_does_not_invent_cost(job, delivery, tokens):
    """usage가 잘못됐는데 임의로 0이나 숫자로 치환하면 원가와 API 이상을 숨긴다."""
    with pytest.raises(llm.GenerationError, match="usage"):
        runner.run_job(job, now=NOW, client=client(input_tokens=tokens))
    record, = records(job)
    assert record.input_tokens is None and record.output_tokens == 200
    assert record.estimated_cost_usd is None and not delivery


def test_missing_secret_has_no_api_cost(job, delivery, monkeypatch):
    """시크릿 누락으로 호출하지 못한 경우와 호출 후 응답 유실을 구별한다."""
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        runner.run_job(job, now=NOW, client=client())
    assert records(job)[0].estimated_cost_usd == 0 and not delivery


def test_missing_usage_is_explicit(job, delivery):
    """SDK 응답 스키마 변경으로 usage가 사라져도 정상 보고로 위장하지 않는다."""
    response = client().messages.create()
    del response.usage
    fake = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: response))
    with pytest.raises(llm.GenerationError):
        runner.run_job(job, now=NOW, client=fake)
    assert records(job)[0].input_tokens is None and not delivery


def test_empty_llm_text_is_not_marked_as_delivered(job, delivery):
    """빈 text 블록은 청크 0개 성공으로 처리되기 쉬우므로 비용을 남기고 실패시킨다."""
    with pytest.raises(llm.GenerationError, match="비어"):
        runner.run_job(job, now=NOW, client=client(text="  \n"))
    record, = records(job)
    assert record.status == "failed" and record.estimated_cost_usd == Decimal("0.010")
    assert not delivery


def test_unexpected_cache_usage_is_not_underpriced(job, delivery):
    """미지원 캐시 요금을 일반 입력 요금만으로 계산해 원가를 낮추면 안 된다."""
    response = client().messages.create()
    response.usage.cache_read_input_tokens = 100
    with pytest.raises(llm.GenerationError, match="캐시"):
        runner.run_job(job, now=NOW, client=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: response)))
    assert records(job)[0].estimated_cost_usd is None and not delivery


def test_bad_telegram_ack_is_failure(job, monkeypatch):
    """HTTP 200이어도 message_id가 없으면 발송 성공 증거로 기록하면 안 된다."""
    monkeypatch.setattr(telegram, "_post", lambda *args: httpx.Response(200, json={"ok": False}))
    with pytest.raises(DeliveryError):
        runner.run_job(job, now=NOW, client=client())
    assert records(job)[0].status == "failed" and records(job)[0].message_ids == []


def test_rate_limit_retry_still_preserves_id(job, monkeypatch):
    """계측을 위해 발송 코드를 고쳐도 기존 429 대기/재시도 방어는 살아 있어야 한다."""
    sleeps = []
    monkeypatch.setattr(telegram.time, "sleep", sleeps.append)
    responses = iter([
        httpx.Response(429, json={"parameters": {"retry_after": 1}}),
        httpx.Response(200, json={"ok": True, "result": {"message_id": 8}}),
    ])
    original = httpx.Client
    transport = httpx.MockTransport(lambda request: next(responses))
    monkeypatch.setattr(telegram.httpx, "Client", lambda **kw: original(transport=transport, **kw))
    runner.run_job(job, now=NOW, client=client())
    assert sleeps == [1] and records(job)[0].message_ids == [8]


def test_actions_rejects_unbacked_up_directory_before_api(job, monkeypatch):
    """YAML 경로 변경으로 Actions 백업에서 이력이 빠지는 것을 조용히 허용하지 않는다."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    job.history.directory = "outside-backup"
    with pytest.raises(history.HistoryError, match=".botkit"):
        runner.run_job(job, now=NOW, client=client())
    assert not Path("outside-backup").exists()


def test_custom_directory_is_available_in_yaml_and_report(job, delivery):
    """고객별 경로를 바꾸려고 Python을 열 필요가 없어야 한다."""
    job.history.directory = ".botkit/acme/history"
    runner.run_job(job, now=NOW, client=client())
    output = CliRunner().invoke(cli, ["report", "--month", "2026-09", "--history-dir", job.history.directory])
    assert output.exit_code == 0 and "0.01000000" in output.output


def test_conflicting_backup_records_fail(job, delivery):
    """동일 ID에 다른 비용이 있는 백업을 합치면 어느 비용도 임의로 선택하면 안 된다."""
    runner.run_job(job, now=NOW, client=client())
    path = history.month_path(job.history.directory, NOW)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["estimated_cost_usd"] = "99"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(data) + "\n")
    with pytest.raises(history.HistoryError):
        records(job)


def test_report_exposes_unknown_cost(job):
    """사용량 미확인 실행이 포함된 합계를 완전한 월 원가로 오해하지 않게 한다."""
    with pytest.raises(httpx.ReadTimeout):
        runner.run_job(job, now=NOW, client=SimpleNamespace(messages=SimpleNamespace(
            create=lambda **kw: (_ for _ in ()).throw(httpx.ReadTimeout("failed"))
        )))
    result = CliRunner().invoke(cli, ["report", "--month", "2026-09"])
    assert result.exit_code == 0 and "unknown" in result.output
    assert "0.00000000\t1" in result.output


def test_validate_checks_price_without_network(job):
    """납품 직전 validate에서 단가 누락을 발견해야 새벽 유료 실행에서 처음 실패하지 않는다."""
    import yaml

    job.prompt.model = "unpriced"
    jobs_dir = Path("config/jobs")
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "acme.yaml").write_text(yaml.safe_dump(job.model_dump()), encoding="utf-8")
    result = CliRunner().invoke(cli, ["validate", "--jobs-dir", str(jobs_dir)])
    assert result.exit_code == 1 and "단가" in result.output


def test_cli_pipeline_with_mocked_external_boundaries(job, monkeypatch):
    """실제 CLI/YAML/HTTP 수집/LLM 어댑터/분할 발송/장부/보고 연결을 비용 없이 검증한다."""
    import yaml

    posts = []
    requests = []

    def http_handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"items": [{"question": "SYNTHETIC INPUT"}]})
        posts.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(posts)}})

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(http_handler), **kw))
    llm_calls = []
    closed = []

    def generate(**kwargs):
        llm_calls.append(kwargs)
        assert "SYNTHETIC INPUT" in kwargs["messages"][0]["content"]
        return client(text="합성 초안 " * 900).messages.create()

    fake = SimpleNamespace(messages=SimpleNamespace(create=generate), close=lambda: closed.append(True))
    monkeypatch.setattr(llm.anthropic, "Anthropic", lambda **kw: fake)
    data = job.model_dump()
    data["source"] = {"type": "http_json", "url": "https://example.invalid/data", "items_path": "items"}
    Path("jobs").mkdir()
    Path("jobs/acme.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    result = CliRunner().invoke(cli, ["run", "--job", "acme", "--jobs-dir", "jobs"])
    assert result.exit_code == 0, result.output
    assert len(llm_calls) == 1 and closed == [True]
    assert len(posts) >= 2 and requests[0].method == "GET"
    assert all(post["chat_id"] == "synthetic-chat" for post in posts)
    month = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    saved, = history.read_month(job.history.directory, month)
    assert saved.message_ids == list(range(1, len(posts) + 1))
    report = CliRunner().invoke(cli, ["report", "--month", month])
    assert report.exit_code == 0 and "0.01000000" in report.output
