"""잡 로컬 복사본의 환경변수 이름만 바인딩한다. 공용 os.environ을 덮어쓰지 않는다."""
from __future__ import annotations

from dataclasses import dataclass

from botkit.jobspec import JobSpec, job_secret_references
from botkit.settings import SecretSelection, check_client_id, select_client_secret


@dataclass(frozen=True)
class JobSecret:
    location: str
    selection: SecretSelection


def inspect_job_secrets(job: JobSpec) -> list[JobSecret]:
    check_client_id(job.client_id)
    return [
        JobSecret(location, select_client_secret(name, job.client_id))
        for location, _, name, _ in job_secret_references(job)
    ]


def bind_job_secrets(job: JobSpec) -> JobSpec:
    """고객 A를 실행한 뒤 고객 B가 A의 설정을 물려받지 않도록 복사본만 수정한다.

    누락은 기존 require_env에서 처리한다. 이 함수는 값이 아닌 선택된 이름만 바꾼다.
    env: 헤더도 같은 규칙을 적용해 validate와 실제 실행의 선택이 일치하게 한다.
    """
    check_client_id(job.client_id)
    bound = job.model_copy(deep=True)
    for _, (target, key), name, is_header in job_secret_references(bound):
        selected = select_client_secret(name, job.client_id)
        resolved = selected.selected_name or selected.scoped_name
        if is_header:
            target[key] = f"env:{resolved}"
        else:
            setattr(target, key, resolved)
    return bound
