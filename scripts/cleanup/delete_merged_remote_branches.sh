#!/usr/bin/env bash
# Delete the remote branches whose entire content is already proven (by
# `git merge-base --is-ancestor`) to be fully absorbed into main or into
# feature/hpms-la-challenger. Nothing here is a judgment call -- these are
# verified pure-ancestor or verified-merged branches. Local copies were
# already deleted. This only touches the GitHub-side refs.
#
# Run this yourself -- branch deletion is gated behind manual approval by
# design (Claude Code's destructive-git-op guard blocks it for an agent).
set -euo pipefail
cd "$(dirname "$0")/../.."

BRANCHES=(
  feature/faf5-network-enrichment
  feature/paraminputs_update
  perf/streaming-arrays-offset-and-vectorize-fix
  feature/freight-passenger-shared-capacity
  feature/conus-nandu-params
  perf/lcp-dest-chunked-dispatch
  perf/pass-a-convergence-diagnosis
  perf/numcpu-regression-diagnosis
  feature/sioux-falls-multihazard
  docs/consolidate-correctness-lessons
  perf/igraph-lookup-tax-fix
)

for b in "${BRANCHES[@]}"; do
  echo "Deleting origin/$b ..."
  git push origin --delete "$b" || echo "  (already gone, or failed -- check manually)"
done
