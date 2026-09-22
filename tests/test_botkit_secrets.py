"""다중 고객 환경에서 이름 선택과 실제 HTTP 요청의 수신 대상이 일치해야 한다."""
import datetime as dt
import json
import os
from pathlib import Path

import httpx
import pytest
import yaml
from click.testing import CliRunner

from botkit import llm, runner, settings
from botkit.cli import cli
from botkit.jobspec import JobConfigError, load_job_file, parse_job
from botkit.secrets import bind_job_secrets, inspect_job_secrets
from botkit.sinks import deliver

NOW = dt.datetime(2026, 9, 21, 23, 5, tzinfo=dt.timezone.utc)
BASE = {
    "client_id": "ACME", "title": "합성 고객",
    "schedule": {"times": ["08:00"]},
    "source": {"type": "static", "rows": [{"question": "synthetic"}]},
    "prompt": {"system": "초안", "user_template": "{rows}"},
    "sinks": [{"type": "telegram"}], "history": {"enabled": False},
}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    """로컬 .env나 개발자의 자격증명 유무가 격리 테스트 결과에 영향을 주지 않게 한다."""
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith(("TELEGRAM_", "SLACK_", "CLIENT_ADMIN_", "CUSTOM_", "ANTHROPIC_")):
            monkeypatch.delenv(name)


def job(owner="ACME", **overrides):
    return parse_job(owner.lower(), {**BASE, "client_id": owner, **overrides})


def write_job(spec):
    Path("jobs").mkdir(exist_ok=True)
    path = Path("jobs") / f"{spec.name}.yaml"
    path.write_text(yaml.safe_dump(spec.model_dump()), encoding="utf-8")
    return path


def configure(monkeypatch, owner):
    monkeypatch.setenv(f"TELEGRAM_BOT_TOKEN__{owner}", f"synthetic-token-{owner}")
    monkeypatch.setenv(f"TELEGRAM_CHAT_ID__{owner}", f"synthetic-chat-{owner}")
    monkeypatch.setenv(f"SLACK_WEBHOOK_URL__{owner}", f"https://example.invalid/hook/{owner}")
    monkeypatch.setenv(f"CLIENT_ADMIN_TOKEN__{owner}", f"synthetic-admin-{owner}")


def mock_http(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[{"question": "synthetic"}])
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(requests)}})

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    return requests


def test_client_id_is_required():
    """고객 식별자를 생략해 공용/다른 고객 설정이 암묵적으로 선택되는 일을 막는다."""
    data = {key: value for key, value in BASE.items() if key != "client_id"}
    with pytest.raises(JobConfigError, match="client_id"):
        parse_job("acme", data)


@pytest.mark.parametrize("bad", ["", "acme", "Acme", " ACME", "ACME ", "A__B", "A-B", "한글", "1ACME", "A_", "A" * 65, None, 12])
def test_invalid_client_id_is_rejected_without_normalizing(bad):
    """접미사 구분자 삽입과 대소문자 정규화 충돌은 고객 시크릿을 혼용시킬 수 있다."""
    with pytest.raises(JobConfigError, match="client_id"):
        job(bad) if isinstance(bad, str) else parse_job("bad", {**BASE, "client_id": bad})


@pytest.mark.parametrize("base", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SLACK_WEBHOOK_URL", "CLIENT_ADMIN_TOKEN"])
def test_scoped_secret_wins_and_no_other_customer_is_looked_up(monkeypatch, base):
    """A의 선택 과정에서 B 값을 한 번도 읽지 않는다는 사실을 조회 목록으로 증명한다."""
    queried = []

    class ObservedEnv(dict):
        def get(self, key, default=None):
            queried.append(key)
            assert not key.endswith("__B")
            return super().get(key, default)

    env = ObservedEnv({base: "shared", f"{base}__ACME": "own", f"{base}__B": "foreign"})
    monkeypatch.setattr(settings.os, "environ", env)
    result = settings.select_client_secret(base, "ACME")
    assert result.selected_name == f"{base}__ACME" and not result.fallback
    assert queried == [f"{base}__ACME"]
    assert "own" not in repr(result) and "foreign" not in repr(result)


@pytest.mark.parametrize("scoped", [None, "", " \n"])
def test_absent_or_blank_scoped_secret_falls_back(monkeypatch, scoped):
    """Actions의 빈 Secret 환경변수도 기존 단일 고객의 공용 설정을 가리지 않아야 한다."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "legacy-shared")
    if scoped is not None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN__ACME", scoped)
    selected = settings.select_client_secret("TELEGRAM_BOT_TOKEN", "ACME")
    assert selected.selected_name == "TELEGRAM_BOT_TOKEN" and selected.fallback


def test_only_other_customer_secret_is_treated_as_missing(monkeypatch):
    """자기 키가 없는 A가 환경변수에 있는 B의 키를 자동 탐색해 쓰면 안 된다."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN__B", "foreign")
    selected = settings.select_client_secret("TELEGRAM_BOT_TOKEN", "ACME")
    assert selected.selected_name is None
    assert (selected.scoped_name, selected.shared_name) == ("TELEGRAM_BOT_TOKEN__ACME", "TELEGRAM_BOT_TOKEN")


@pytest.mark.parametrize("location", ["token", "chat", "url", "source_header", "sink_header"])
def test_explicit_other_customer_reference_is_rejected(location):
    """env 옵션이나 헤더로 B의 이름을 직접 적는 우회 경로까지 로딩 시 차단한다."""
    source = BASE["source"]
    sinks = [{"type": "telegram"}]
    if location in ("token", "chat"):
        sinks[0]["bot_token_env" if location == "token" else "chat_id_env"] = "TELEGRAM_BOT_TOKEN__B"
    elif location == "url":
        sinks = [{"type": "webhook", "url_env": "SLACK_WEBHOOK_URL__B"}]
    elif location == "source_header":
        source = {"type": "http_json", "url": "https://example.invalid", "headers": {"Authorization": "env:TELEGRAM_BOT_TOKEN__B"}}
    else:
        sinks = [{"type": "webhook", "url_env": "SLACK_WEBHOOK_URL", "headers": {"Authorization": "env:TELEGRAM_BOT_TOKEN__B"}}]
    with pytest.raises(JobConfigError, match="다른 고객"):
        job(source=source, sinks=sinks)


@pytest.mark.parametrize("bad_name", ["TOKEN___ACME", "TOKEN__ACME__B", "token", "TOKEN_", "env:TOKEN", "TOKEN NAME"])
def test_ambiguous_env_names_are_rejected(bad_name):
    """구분자·대소문자·빈칸이 있는 이름을 조용히 보정하면 다른 환경변수를 읽을 수 있다."""
    with pytest.raises(JobConfigError):
        job(sinks=[{"type": "telegram", "bot_token_env": bad_name}])


def test_explicit_own_namespace_and_custom_base_are_supported(monkeypatch):
    """자기 접미사를 명시한 YAML과 기존 사용자 정의 기본 변수명도 안전하게 유지한다."""
    monkeypatch.setenv("CUSTOM_BOT__ACME", "own")
    spec = job(sinks=[{"type": "telegram", "bot_token_env": "CUSTOM_BOT__ACME"}])
    bound = bind_job_secrets(spec)
    assert bound.sinks[0].bot_token_env == "CUSTOM_BOT__ACME"
    assert bind_job_secrets(bound).sinks[0].bot_token_env == "CUSTOM_BOT__ACME"


def test_binding_does_not_mutate_shared_environment_or_job(monkeypatch):
    """A 실행을 위해 os.environ/공용 JobSpec을 바꾸면 뒤의 B 실행에 A 토큰이 남는다."""
    configure(monkeypatch, "ACME")
    configure(monkeypatch, "B")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "shared")
    first = job()
    second = first.model_copy(update={"client_id": "B"})
    before = dict(os.environ)
    a, b = bind_job_secrets(first), bind_job_secrets(second)
    assert a.sinks[0].bot_token_env == "TELEGRAM_BOT_TOKEN__ACME"
    assert b.sinks[0].bot_token_env == "TELEGRAM_BOT_TOKEN__B"
    assert first.sinks[0].bot_token_env == second.sinks[0].bot_token_env == "TELEGRAM_BOT_TOKEN"
    assert dict(os.environ) == before


def test_runtime_rejects_foreign_reference_even_after_model_copy(monkeypatch):
    """검증을 생략하는 model_copy로 바뀐 잡도 네트워크 경계에서 B를 참조하면 안 된다."""
    configure(monkeypatch, "B")
    spec = job()
    spec.sinks[0].bot_token_env = "TELEGRAM_BOT_TOKEN__B"
    monkeypatch.setattr(runner, "fetch_rows", lambda source: pytest.fail("수집 전 차단 필요"))
    with pytest.raises(ValueError, match="다른 고객"):
        runner.run_job(spec, now=NOW)
    with pytest.raises(ValueError, match="다른 고객"):
        deliver(spec, "draft", NOW)


def test_real_adapters_use_only_each_customers_credentials(monkeypatch):
    """선택 함수만 맞아도 실제 발송이 공용 이름을 읽으면 실패하므로 HTTP까지 검증한다."""
    configure(monkeypatch, "ACME")
    configure(monkeypatch, "B")
    requests = mock_http(monkeypatch)
    monkeypatch.setattr(llm, "generate", lambda *a, **k: llm.GenerationResult("합성 초안", 10, 5))
    for owner in ("ACME", "B", "ACME"):
        spec = job(owner,
            source={"type": "http_json", "url": "https://example.invalid/data", "headers": {"Authorization": "env:CLIENT_ADMIN_TOKEN"}},
            sinks=[{"type": "telegram"}, {"type": "webhook", "url_env": "SLACK_WEBHOOK_URL", "headers": {"Authorization": "env:CLIENT_ADMIN_TOKEN"}}],
        )
        assert runner.run_job(spec, now=NOW).status == "ok"
    assert len(requests) == 9
    for index, owner in enumerate(("ACME", "B", "ACME")):
        source, telegram, webhook = requests[index * 3:index * 3 + 3]
        assert source.headers["Authorization"] == f"synthetic-admin-{owner}"
        assert telegram.url.path == f"/botsynthetic-token-{owner}/sendMessage"
        assert json.loads(telegram.content)["chat_id"] == f"synthetic-chat-{owner}"
        assert webhook.url.path == f"/hook/{owner}"
        assert webhook.headers["Authorization"] == f"synthetic-admin-{owner}"


def test_missing_a_secret_does_not_borrow_b_or_stop_b(monkeypatch, tmp_path):
    """A의 키 교체/삭제가 B의 정상 보고까지 중단하거나 B 토큰 대여로 이어지면 안 된다."""
    configure(monkeypatch, "B")
    requests = mock_http(monkeypatch)
    monkeypatch.setattr(llm, "generate", lambda *a, **k: llm.GenerationResult("draft", 1, 1))
    results = runner.run_due([job(), job("B")], now=NOW, state_path=tmp_path / "state.json")
    assert [result.status for result in results] == ["failed", "ok"]
    assert len(requests) == 1 and requests[0].url.path == "/botsynthetic-token-B/sendMessage"


@pytest.mark.parametrize("command", ["run", "test-telegram"])
def test_cli_execution_paths_use_customer_binding(monkeypatch, command):
    """연결 테스트만 공용 봇으로 나가거나 수동 실행만 격리를 우회하면 납품 검증이 틀린다."""
    configure(monkeypatch, "ACME")
    write_job(job())
    requests = mock_http(monkeypatch)
    monkeypatch.setattr(llm, "generate", lambda *a, **k: llm.GenerationResult("draft", 1, 1))
    result = CliRunner().invoke(cli, [command, "--job", "acme", "--jobs-dir", "jobs"])
    assert result.exit_code == 0, result.output
    assert requests[0].url.path == "/botsynthetic-token-ACME/sendMessage"
    assert json.loads(requests[0].content)["chat_id"] == "synthetic-chat-ACME"


def test_validate_shows_selected_names_and_fallback_but_no_values(monkeypatch):
    """납품 전에 실제 선택된 이름/공용 폴백을 보여주되 토큰과 URL은 로그에 남기지 않는다."""
    configure(monkeypatch, "ACME")
    monkeypatch.delenv("TELEGRAM_CHAT_ID__ACME")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "synthetic-shared-chat")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-llm")
    write_job(job(sinks=[{"type": "telegram"}, {"type": "webhook", "url_env": "SLACK_WEBHOOK_URL", "headers": {"Authorization": "env:CLIENT_ADMIN_TOKEN"}}]))
    result = CliRunner().invoke(cli, ["validate", "--jobs-dir", "jobs"])
    assert result.exit_code == 0, result.output
    assert "TELEGRAM_BOT_TOKEN__ACME (고객 전용)" in result.output
    assert "TELEGRAM_CHAT_ID (공용 폴백)" in result.output
    assert "SLACK_WEBHOOK_URL__ACME (고객 전용)" in result.output
    assert "CLIENT_ADMIN_TOKEN__ACME (고객 전용)" in result.output
    assert "synthetic-" not in result.output and "https://" not in result.output


def test_validate_missing_names_does_not_claim_a_selection(monkeypatch):
    """누락과 폴백을 구별하지 않으면 운영자가 전용 설정이 적용됐다고 오인한다."""
    configure(monkeypatch, "B")
    write_job(job())
    result = CliRunner().invoke(cli, ["validate", "--jobs-dir", "jobs"])
    assert result.exit_code == 1 and "누락" in result.output
    assert "TELEGRAM_BOT_TOKEN__ACME / TELEGRAM_BOT_TOKEN" in result.output
    assert "__B" not in result.output and "공용 폴백" not in result.output


def test_header_references_share_validate_and_runtime_resolution(monkeypatch):
    """소스 헤더와 웹훅 헤더 누락도 validate가 잡아 실행 때 처음 실패하지 않게 한다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-llm")
    configure(monkeypatch, "ACME")
    spec = job(source={"type": "http_json", "url": "https://example.invalid", "headers": {"Authorization": "env:CLIENT_ADMIN_TOKEN"}})
    report = inspect_job_secrets(spec)
    assert report[-1].selection.selected_name == "CLIENT_ADMIN_TOKEN__ACME"
    assert bind_job_secrets(spec).source.headers["Authorization"] == "env:CLIENT_ADMIN_TOKEN__ACME"
    monkeypatch.delenv("CLIENT_ADMIN_TOKEN__ACME")
    write_job(spec)
    result = CliRunner().invoke(cli, ["validate", "--jobs-dir", "jobs"])
    assert result.exit_code == 1 and "source.headers.Authorization: 누락" in result.output


def test_examples_and_template_have_required_client_and_remain_disabled():
    """기존 납품 템플릿이 필수 필드 추가로 깨지거나 예시가 자동 활성화되면 안 된다."""
    root = Path(__file__).resolve().parents[1]
    jobs = [load_job_file(path) for path in (root / "config/jobs").glob("*.yaml")]
    assert len(jobs) == 4 and all(item.client_id == "ACME" for item in jobs)
    assert all(not item.enabled for item in jobs if item.name.startswith("example_"))


def test_scoped_env_names_are_registered_in_both_local_and_actions():
    """로컬에만 전용 키를 등록해 Actions에서 공용으로 폴백하는 배포 사고를 막는다."""
    root = Path(__file__).resolve().parents[1]
    env_names = {line.split("=", 1)[0] for line in (root / ".env.example").read_text(encoding="utf-8").splitlines() if "=" in line and not line.startswith("#")}
    workflow = yaml.safe_load((root / ".github/workflows/botkit.yml").read_text(encoding="utf-8"))
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SLACK_WEBHOOK_URL", "CLIENT_ADMIN_TOKEN"):
        scoped = name + "__ACME"
        assert scoped in env_names
        assert workflow["jobs"]["run"]["env"][scoped] == "${{ secrets." + scoped + " }}"
