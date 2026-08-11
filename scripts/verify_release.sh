#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
verify_dir="$(mktemp -d "${TMPDIR:-/tmp}/ecoguard-verify.XXXXXX")"
trap 'rm -rf "$verify_dir"' EXIT

export LC_ALL=C.UTF-8
export PYTHONHASHSEED=0
export TZ=UTC

cd "$repo_dir"
PYTHONPATH="$repo_dir/src" python3 -m unittest discover -s tests -v
PYTHONPATH="$repo_dir/src" python3 -m compileall -q src tests

python3 -m pip wheel \
  --disable-pip-version-check \
  --no-deps \
  --no-build-isolation \
  --wheel-dir "$verify_dir/wheel" \
  "$repo_dir"

python3 -m venv "$verify_dir/venv"
wheel_path=("$verify_dir"/wheel/*.whl)
"$verify_dir/venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-deps \
  "${wheel_path[0]}"

cd "$repo_dir"
"$verify_dir/venv/bin/python" -m unittest discover -s tests -v

mkdir -p "$verify_dir/runtime"
cd "$verify_dir/runtime"
"$verify_dir/venv/bin/python" -m ecoguard reproduce \
  --output "$verify_dir/generated"

diff -ru "$repo_dir/artifacts/examples" "$verify_dir/generated"

cd "$repo_dir"
git diff --check

echo "EcoGuard release verification passed."
echo "- unit tests: source tree and installed wheel"
echo "- wheel: ${wheel_path[0]}"
echo "- runtime cwd: $verify_dir/runtime"
echo "- golden artifacts: byte-identical"
