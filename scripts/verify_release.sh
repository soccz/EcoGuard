#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
verify_dir="$(mktemp -d "${TMPDIR:-/tmp}/ecoguard-verify.XXXXXX")"
trap 'rm -rf "$verify_dir"' EXIT

export LC_ALL=C.UTF-8
export PYTHONHASHSEED=0
export TZ=UTC
umask 022

if ! git -C "$repo_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Release verification requires a Git worktree." >&2
  exit 1
fi

# A release must describe HEAD exactly. Ignored local environments and generated
# artifacts are harmless because the snapshot below only copies tracked files;
# tracked changes and non-ignored untracked files are refused. Recheck after
# source verification and at the end so a tool cannot mutate the release input.
require_clean_worktree() {
  local phase="$1"
  local status

  status="$(git -C "$repo_dir" status --porcelain=v1 --untracked-files=all)"
  if [[ -n "$status" ]]; then
    echo "Release verification requires a clean worktree during $phase." >&2
    echo "Commit, stash, or remove these tracked/untracked changes:" >&2
    printf '%s\n' "$status" >&2
    exit 1
  fi
}

require_clean_worktree "startup"

source_date_epoch="$(git -C "$repo_dir" show -s --format=%ct HEAD)"
if [[ ! "$source_date_epoch" =~ ^[0-9]+$ ]]; then
  echo "Could not derive SOURCE_DATE_EPOCH from HEAD." >&2
  exit 1
fi
export SOURCE_DATE_EPOCH="$source_date_epoch"

cd "$repo_dir"
python3 -m venv "$verify_dir/tooling"
"$verify_dir/tooling/bin/python" -m pip install \
  --disable-pip-version-check \
  "$repo_dir[dev]"

COVERAGE_FILE="$verify_dir/.coverage" \
  PYTHONPATH="$repo_dir/src" \
  "$verify_dir/tooling/bin/python" -m coverage run \
  -m unittest discover -s tests -v
COVERAGE_FILE="$verify_dir/.coverage" \
  "$verify_dir/tooling/bin/python" -m coverage report
PYTHONPATH="$repo_dir/src" \
  "$verify_dir/tooling/bin/python" -m compileall -q src tests
"$verify_dir/tooling/bin/python" -m compileall -q \
  scripts/benchmark_ocr.py \
  research/forest_xai
"$verify_dir/tooling/bin/python" -m ruff check \
  src tests scripts/benchmark_ocr.py research/forest_xai
"$verify_dir/tooling/bin/python" -m black --check \
  src tests scripts/benchmark_ocr.py research/forest_xai
bash -n scripts/*.sh
require_clean_worktree "source verification"

# Export two independent source trees from the committed Git object. This
# excludes ignored/untracked residue and normalizes tracked file modes and
# timestamps across worktrees before the wheel builder sees them.
export_tracked_source() {
  local destination="$1"

  mkdir -p "$destination"
  git -C "$repo_dir" archive --format=tar HEAD | tar -xf - -C "$destination"
}

source_one="$verify_dir/source-one"
source_two="$verify_dir/source-two"
export_tracked_source "$source_one"
export_tracked_source "$source_two"

"$verify_dir/tooling/bin/python" -m pip wheel \
  --disable-pip-version-check \
  --no-deps \
  --wheel-dir "$verify_dir/wheel-one" \
  "$source_one"
"$verify_dir/tooling/bin/python" -m pip wheel \
  --disable-pip-version-check \
  --no-deps \
  --wheel-dir "$verify_dir/wheel-two" \
  "$source_two"

shopt -s nullglob
wheel_one=("$verify_dir"/wheel-one/*.whl)
wheel_two=("$verify_dir"/wheel-two/*.whl)
shopt -u nullglob
if (( ${#wheel_one[@]} != 1 || ${#wheel_two[@]} != 1 )); then
  echo "Expected exactly one wheel from each clean build." >&2
  exit 1
fi
if [[ "$(basename "${wheel_one[0]}")" != "$(basename "${wheel_two[0]}")" ]]; then
  echo "Clean builds produced different wheel filenames." >&2
  exit 1
fi
if ! cmp -s "${wheel_one[0]}" "${wheel_two[0]}"; then
  echo "Clean builds produced different wheel bytes." >&2
  sha256sum "${wheel_one[0]}" "${wheel_two[0]}" >&2
  exit 1
fi
wheel_sha256="$(sha256sum "${wheel_one[0]}" | cut -d ' ' -f 1)"

if [[ -n "${ECOGUARD_RELEASE_DIST:-}" ]]; then
  if [[ "$ECOGUARD_RELEASE_DIST" != /* ]]; then
    echo "ECOGUARD_RELEASE_DIST must be an absolute path." >&2
    exit 1
  fi
  mkdir -p "$ECOGUARD_RELEASE_DIST"
  cp "${wheel_one[0]}" "$ECOGUARD_RELEASE_DIST/"
fi

python3 -m venv "$verify_dir/venv"
"$verify_dir/venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-deps \
  "${wheel_one[0]}"
"$verify_dir/venv/bin/python" -m pip install \
  --disable-pip-version-check \
  "hypothesis==6.165.3" \
  "jsonschema==4.26.0"

cd "$repo_dir"
env -u PYTHONPATH PYTHONNOUSERSITE=1 \
  "$verify_dir/venv/bin/python" -m unittest discover -s tests -v

mkdir -p "$verify_dir/runtime"
cd "$verify_dir/runtime"
env -u PYTHONPATH PYTHONNOUSERSITE=1 \
  "$verify_dir/venv/bin/python" -m ecoguard reproduce \
  --output "$verify_dir/generated"
env -u PYTHONPATH PYTHONNOUSERSITE=1 \
  "$verify_dir/venv/bin/python" -m ecoguard benchmark \
  --root "$repo_dir" \
  --output "$verify_dir/generated-benchmarks"

diff -ru "$repo_dir/artifacts/examples" "$verify_dir/generated"
diff -ru "$repo_dir/artifacts/benchmarks" "$verify_dir/generated-benchmarks"

cd "$repo_dir"
git diff --check
require_clean_worktree "final verification"

echo "EcoGuard release verification passed."
echo "- lint/format/coverage: Ruff, Black and branch coverage threshold"
echo "- unit/schema tests: source tree and installed wheel"
echo "- source snapshot: canonical Git archive from clean HEAD"
echo "- reproducible wheel SHA-256: $wheel_sha256"
echo "- runtime cwd: $verify_dir/runtime"
echo "- evidence and benchmark artifacts: byte-identical"
