"""CLI 진입점 (`botkit` 커맨드). 납품/운영 중 실제로 두드리는 명령들."""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

import click

from botkit.jobspec import JOBS_DIR, JobConfigError, TelegramSink, load_job, load_jobs
from botkit.schedule import DEFAULT_TICK_MINUTES, describe, due_at
from botkit.settings import load_env_file
from botkit.sinks import telegram
from botkit.runner import run_due, run_job
from botkit.history import HistoryError, read_month, summarize
from botkit.pricing import PricingError, load_price
from botkit.secrets import bind_job_secrets, inspect_job_secrets

jobs_dir_option = click.option(
    "--jobs-dir",
    type=click.Path(path_type=Path),
    default=None,
    help=f"잡 YAML 디렉터리 (기본: {JOBS_DIR})",
)


@click.group()
def cli() -> None:
    """고객사 업무 자동화 봇 실행기."""
    # 로컬에서는 .env를, Actions에서는 Secrets를 쓴다. 이미 설정된 환경변수가
    # 우선이라 두 경로가 충돌하지 않는다.
    load_env_file()


@cli.command("list")
@jobs_dir_option
def list_jobs(jobs_dir: Path | None) -> None:
    """등록된 잡 목록과 스케줄."""
    jobs = load_jobs(jobs_dir)
    if not jobs:
        click.echo("잡이 없습니다. config/jobs/*.yaml을 추가하세요.")
        return
    for job in jobs:
        flag = " " if job.enabled else "x"
        click.echo(f"[{flag}] {job.name}: {job.title} (client_id={job.client_id})")
        click.echo(f"      스케줄: {describe(job.schedule)}")
        click.echo(f"      소스: {job.source.type} -> 싱크: {', '.join(s.type for s in job.sinks)}")


@cli.command()
@jobs_dir_option
def validate(jobs_dir: Path | None) -> None:
    """납품 전 점검: YAML 스키마 + 필요한 환경변수가 채워졌는지."""
    try:
        jobs = load_jobs(jobs_dir)
    except JobConfigError as exc:
        click.echo(f"설정 오류:\n{exc}")
        sys.exit(1)

    missing_total = 0
    pricing_errors = 0
    for job in jobs:
        missing = []
        click.echo(f"{job.name}: client_id={job.client_id}")
        llm_present = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
        click.echo(f"  Claude: ANTHROPIC_API_KEY ({'공용' if llm_present else '누락'})")
        if not llm_present:
            missing.append("ANTHROPIC_API_KEY")
        for reference in inspect_job_secrets(job):
            selection = reference.selection
            if selection.selected_name is None:
                names = f"{selection.scoped_name} / {selection.shared_name}"
                missing.append(names)
                click.echo(f"  {reference.location}: 누락 ({names})")
            else:
                mode = "공용 폴백" if selection.fallback else "고객 전용"
                click.echo(f"  {reference.location}: {selection.selected_name} ({mode})")
        missing_total += len(missing)
        status = "OK" if not missing else f"환경변수 누락: {', '.join(missing)}"
        click.echo(f"{job.name}: 스키마 OK / {status}")
        if job.history.enabled:
            try:
                load_price(job.history.pricing_file, job.prompt.model)
            except PricingError as exc:
                pricing_errors += 1
                click.echo(f"{job.name}: {exc}")

    click.echo(f"\n잡 {len(jobs)}개 검증 완료.")
    if missing_total:
        click.echo("환경변수가 비어 있으면 실행 시점에 실패합니다 (.env 또는 Actions Secrets 확인).")
    if missing_total or pricing_errors:
        sys.exit(1)


@cli.command()
@click.option("--job", "job_name", default="", help="실행할 잡 이름 (config/jobs/<이름>.yaml)")
@click.option("--due-now", is_flag=True, help="지금 예정 시각인 잡만 실행 (스케줄러 진입점)")
@click.option("--dry-run", is_flag=True, help="발송하지 않고 생성 결과만 출력")
@click.option(
    "--tick-minutes",
    default=DEFAULT_TICK_MINUTES,
    help="--due-now 판정 구간(분). 워크플로 cron 간격과 같게 맞춘다.",
)
@click.option(
    "--state-file",
    type=click.Path(path_type=Path),
    default=None,
    help="중복 발송 방지용 상태 파일 (--due-now와 함께 사용)",
)
@jobs_dir_option
def run(
    job_name: str,
    due_now: bool,
    dry_run: bool,
    tick_minutes: int,
    state_file: Path | None,
    jobs_dir: Path | None,
) -> None:
    """잡 실행. --job은 즉시 1회, --due-now는 스케줄에 걸린 잡만."""
    if bool(job_name) == due_now:
        raise click.UsageError("--job 과 --due-now 중 하나만 지정하세요.")

    if job_name:
        job = load_job(job_name, jobs_dir)
        try:
            results = [run_job(job, dry_run=dry_run)]
        except Exception as exc:  # noqa: BLE001 - CLI 경계에서 사유를 보여주고 종료
            click.echo(f"{job.name}: 실패 - {type(exc).__name__}: {exc}")
            sys.exit(1)
    else:
        results = run_due(
            load_jobs(jobs_dir),
            tick_minutes=tick_minutes,
            state_path=state_file,
            dry_run=dry_run,
        )
        if not results:
            click.echo("지금 예정된 잡이 없습니다.")

    for result in results:
        click.echo(f"{result.job_name}: {result.status} (수집 {result.row_count}건) {result.reason}".rstrip())
        for line in result.deliveries:
            click.echo(f"  - {line}")
        if result.history_id:
            click.echo(f"  - history_id={result.history_id}")
        if result.ledger_error:
            # 발송은 됐지만 장부가 비었다. 상태를 실패로 바꾸면 다음 tick에
            # 중복 발송이 되므로, 알림은 종료 코드로만 올린다.
            click.echo(f"  - 이력 저장 실패(발송은 완료): {result.ledger_error}")
        if dry_run and result.output:
            click.echo("--- 생성 결과 ---")
            click.echo(result.output)

    if any(result.needs_operator for result in results):
        sys.exit(1)


@cli.command("test-telegram")
@click.option("--job", "job_name", required=True, help="이 잡의 텔레그램 설정으로 테스트 발송")
@jobs_dir_option
def test_telegram(job_name: str, jobs_dir: Path | None) -> None:
    """납품 직전 확인용: 고객 채팅방으로 테스트 메시지 1건 발송."""
    job = bind_job_secrets(load_job(job_name, jobs_dir))
    sinks = [s for s in job.sinks if isinstance(s, TelegramSink)]
    if not sinks:
        click.echo(f"{job.name}에는 텔레그램 싱크가 없습니다.")
        sys.exit(1)

    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    for sink in sinks:
        ids = telegram.send(
            sink,
            f"[연결 테스트] {job.title}\n"
            f"{stamp} 기준으로 봇 연결이 정상입니다.\n"
            f"예정 발송: {describe(job.schedule)}",
        )
        click.echo(f"{job.name}: 발송 완료 (message_id={ids})")


@cli.command()
@click.option("--tick-minutes", default=DEFAULT_TICK_MINUTES, help="판정 구간(분)")
@jobs_dir_option
def due(tick_minutes: int, jobs_dir: Path | None) -> None:
    """지금 실행 대상인 잡을 확인만 한다 (스케줄 디버깅용)."""
    now = dt.datetime.now(dt.timezone.utc)
    for job in load_jobs(jobs_dir):
        fire_at = due_at(job.schedule, now, tick_minutes) if job.enabled else None
        mark = f"실행 대상 ({fire_at:%Y-%m-%d %H:%M} 분)" if fire_at else "대기"
        click.echo(f"{job.name}: {mark}")


@cli.command()
@click.option("--month", required=True, help="조회할 UTC 회차 월 (YYYY-MM)")
@click.option("--history-dir", type=click.Path(path_type=Path), default=Path(".botkit/history"))
def report(month: str, history_dir: Path) -> None:
    """잡별 실행 상태, 토큰 사용량과 추정 원가 (dry-run/실패 비용 포함)."""
    try:
        records = read_month(history_dir, month)
    except HistoryError as exc:
        raise click.ClickException(str(exc)) from exc
    if not records:
        click.echo("이력이 없습니다. 0원 사용을 뜻하지 않습니다. 경로와 백업 복원을 확인하세요.")
        return
    click.echo("job\truns\tok\tskipped\tfailed\tdry-run\tinput_tokens\toutput_tokens\tUSD\tunknown")
    for name, item in sorted(summarize(records).items()):
        click.echo(
            f"{name}\t{item.runs}\t{item.statuses['ok']}\t{item.statuses['skipped']}\t"
            f"{item.statuses['failed']}\t{item.statuses['dry-run']}\t{item.input_tokens}\t"
            f"{item.output_tokens}\t{item.estimated_cost_usd:.8f}\t{item.unknown_cost_runs}"
        )
    click.echo("USD는 기록된 단가의 추정 합계입니다. unknown은 비용 미확인 건수(합계 제외)입니다.")
    click.echo("입력/출력 본문은 저장하지 않습니다. API 청구서와 별도로 대조하세요.")


if __name__ == "__main__":
    cli()
