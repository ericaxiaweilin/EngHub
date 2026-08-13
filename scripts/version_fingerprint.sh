#!/usr/bin/env bash
# Print the source fingerprint used to identify an EngHub deployment.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

commit="$(git rev-parse HEAD 2>/dev/null || true)"
tree="$(git rev-parse HEAD^{tree} 2>/dev/null || true)"
status="$(git status --porcelain=v1 2>/dev/null || true)"

if [[ -z "$commit" || -z "$tree" ]]; then
  echo "git_commit=unavailable"
  echo "git_tree=unavailable"
  echo "worktree=unavailable"
  exit 1
fi

echo "git_commit=$commit"
echo "git_tree=$tree"
echo "release_fingerprint=enghub-${commit:0:12}"
if [[ -n "$status" ]]; then
  echo "worktree=dirty"
else
  echo "worktree=clean"
fi
