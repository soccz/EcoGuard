#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

PYTHONPATH="$repo_dir/src" python3 -m unittest discover -s tests -v
PYTHONPATH="$repo_dir/src" python3 -m ecoguard reproduce --output artifacts/generated

echo "Generated artifacts: $repo_dir/artifacts/generated"
