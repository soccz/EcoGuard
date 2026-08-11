#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
verify_dir="$(mktemp -d "${TMPDIR:-/tmp}/ecoguard-verify.XXXXXX")"
trap 'rm -rf "$verify_dir"' EXIT

export LC_ALL=C.UTF-8
export PYTHONHASHSEED=0
export TZ=UTC

cd "$repo_dir"
python3 -m venv "$verify_dir/tooling"
"$verify_dir/tooling/bin/python" -m pip install \
  --disable-pip-version-check \
  "$repo_dir[dev]"

PYTHONPATH="$repo_dir/src" \
  "$verify_dir/tooling/bin/python" -m unittest discover -s tests -v
PYTHONPATH="$repo_dir/src" \
  "$verify_dir/tooling/bin/python" -m compileall -q src tests
"$verify_dir/tooling/bin/python" -m ruff check src tests
"$verify_dir/tooling/bin/python" -m black --check src tests

# Build from an explicit public-file snapshot so an ignored, stale build/
# directory can never leak a deleted resource back into the release wheel.
source_dir="$verify_dir/source"
mkdir -p "$source_dir"
while IFS= read -r -d '' source_path; do
  mkdir -p "$source_dir/$(dirname "$source_path")"
  cp -a "$repo_dir/$source_path" "$source_dir/$source_path"
done < <(git ls-files --cached --others --exclude-standard -z)

"$verify_dir/tooling/bin/python" -m pip wheel \
  --disable-pip-version-check \
  --no-deps \
  --wheel-dir "$verify_dir/wheel" \
  "$source_dir"

python3 -m venv "$verify_dir/venv"
wheel_path=("$verify_dir"/wheel/*.whl)
"$verify_dir/venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-deps \
  "${wheel_path[0]}"
"$verify_dir/venv/bin/python" -m pip install \
  --disable-pip-version-check \
  "jsonschema==4.26.0"

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
echo "- lint/format: Ruff and Black"
echo "- unit/schema tests: source tree and installed wheel"
echo "- wheel: ${wheel_path[0]}"
echo "- runtime cwd: $verify_dir/runtime"
echo "- golden artifacts: byte-identical"
