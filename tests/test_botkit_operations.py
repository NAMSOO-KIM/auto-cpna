"""보일러플레이트의 배포 경계는 실제 Actions 설정과 함께 검증한다."""
import ast
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_botkit_keeps_five_package_boundary():
    """고객 납품본에 autocpna/DB 의존성이 섞이면 YAML 한 장 납품이 깨진다."""
    allowed = sys.stdlib_module_names | {"botkit", "anthropic", "httpx", "pydantic", "yaml", "click"}
    for path in (ROOT / "src" / "botkit").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [entry.name.split(".")[0] for entry in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module.split(".")[0]] if node.module else []
            else:
                continue
            assert set(modules) <= allowed, (path, modules)


def test_workflow_retains_history_on_manual_dry_and_failed_runs():
    """로컬만 장부가 남고 Actions에서는 수동/실패 비용이 사라지는 사고를 막는다."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/botkit.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["run"]["steps"]
    save, = [step for step in steps if step.get("uses", "").startswith("actions/cache/save")]
    artifact, = [step for step in steps if step.get("uses", "").startswith("actions/upload-artifact")]
    assert save["if"] == artifact["if"] == "always()"
    assert "github.run_attempt" in save["with"]["key"]
    assert artifact["with"]["path"] == ".botkit/"
    assert artifact["with"]["include-hidden-files"] is True
    assert workflow["concurrency"]["cancel-in-progress"] is False
    notification, = [step for step in steps if step.get("name") == "Notify operator on failure"]
    assert notification["env"]["OPS_CHAT_ID"] == "${{ secrets.OPS_TELEGRAM_CHAT_ID }}"
    assert "$OPS_CHAT_ID" in notification["run"] and "$TELEGRAM_CHAT_ID" not in notification["run"]


def test_new_input_env_is_documented_and_not_shell_interpolated():
    """새 환경변수 누락과 workflow 입력이 쉘 코드가 되는 문제를 동시에 방지한다."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/botkit.yml").read_text(encoding="utf-8"))
    run = workflow["jobs"]["run"]
    assert run["env"]["BOTKIT_JOB"] == "${{ inputs.job }}"
    assert "BOTKIT_JOB=" in (ROOT / ".env.example").read_text(encoding="utf-8")
    step, = [step for step in run["steps"] if step.get("name") == "Run one job"]
    assert '${{ inputs.job }}' not in step["run"]
    assert '"$BOTKIT_JOB"' in step["run"]
