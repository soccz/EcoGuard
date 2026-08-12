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

PYTHONPATH="$repo_dir/src" \
  "$verify_dir/tooling/bin/python" -m unittest discover -s tests -v
PYTHONPATH="$repo_dir/src" \
  "$verify_dir/tooling/bin/python" -m compileall -q src tests
"$verify_dir/tooling/bin/python" -m ruff check src tests
"$verify_dir/tooling/bin/python" -m black --check src tests
require_clean_worktree "source verification"

# Make two independent snapshots from Git's tracked-file allow-list. Neither
# ignored build residue nor an untracked local file can enter a release wheel.
copy_tracked_source() {
  local destination="$1"
  local source_path

  mkdir -p "$destination"
  while IFS= read -r -d '' source_path; do
    mkdir -p "$destination/$(dirname "$source_path")"
    cp -a "$repo_dir/$source_path" "$destination/$source_path"
  done < <(git -C "$repo_dir" ls-files --cached -z)
}

source_one="$verify_dir/source-one"
source_two="$verify_dir/source-two"
copy_tracked_source "$source_one"
copy_tracked_source "$source_two"

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

python3 -m venv "$verify_dir/venv"
"$verify_dir/venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-deps \
  "${wheel_one[0]}"
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
require_clean_worktree "final verification"

echo "EcoGuard release verification passed."
echo "- lint/format: Ruff and Black"
echo "- unit/schema tests: source tree and installed wheel"
echo "- source snapshot: Git-tracked files from clean HEAD"
echo "- reproducible wheel SHA-256: $wheel_sha256"
echo "- runtime cwd: $verify_dir/runtime"
echo "- golden artifacts: byte-identical"
