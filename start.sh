#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -x .venv/bin/python ]; then
    exec .venv/bin/python -m wedecide.cli serve "$@"
fi
exec python3 -m wedecide.cli serve "$@"
