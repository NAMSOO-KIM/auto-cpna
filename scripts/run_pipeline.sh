#!/usr/bin/env bash
# 스코어링 -> 콘텐츠 생성까지 자동 실행 (발행은 사람 승인 후 별도 실행)
set -euo pipefail

autocpna score --keyword "${1:-}"
autocpna generate --top "${2:-10}"
autocpna review list
