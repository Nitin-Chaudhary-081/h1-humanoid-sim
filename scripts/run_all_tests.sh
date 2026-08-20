#!/usr/bin/env bash
# run_all_tests.sh — aggregate pure-pytest runner for every h1 package (M8 gate).
#
# For each package in src/ with a test/ dir containing test_*.py, runs
#   cd src/<pkg> && PYTHONPATH=src python3 -m pytest test/ -q
# (the documented acceptance command in each package's test files),
# then prints a summary table: package | tests run | passed | failed | time.
#
# Pure logic tests only — no ROS, no network, no sim. Idempotent / read-only.
# Exit code: 0 if every suite passed, 1 otherwise.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Dependency order: contract/interface consumers before producers' consumers;
# telemetry before aws_sync (sync consumes data/telemetry.jsonl).
PACKAGES=(h1_control h1_llm_agent h1_telemetry h1_visualization \
          h1_perception h1_grasp_pipeline h1_moveit_follower h1_aws_sync)

# Auto-append any other package with tests not in the list above.
for p in src/*/; do
  pkg="$(basename "$p")"
  case " ${PACKAGES[*]} " in
    *" $pkg "*) ;;
    *)
      if [ -d "src/$pkg/test" ] && ls src/"$pkg"/test/test_*.py >/dev/null 2>&1; then
        PACKAGES+=("$pkg")
      fi
      ;;
  esac
done

overall_fail=0
skipped=0
rows=()

for pkg in "${PACKAGES[@]}"; do
  if [ ! -d "src/$pkg/test" ]; then
    echo "SKIP   ${pkg}: no test/ dir (nothing to run)"
    skipped=$((skipped + 1))
    continue
  fi
  if ! ls src/"$pkg"/test/test_*.py >/dev/null 2>&1; then
    echo "SKIP   ${pkg}: test/ dir has no test_*.py files"
    skipped=$((skipped + 1))
    continue
  fi

  start_s=$(date +%s)
  out="$(mktemp)"
  (cd "src/$pkg" && PYTHONPATH=src python3 -m pytest test/ -q) >"$out" 2>&1
  rc=$?
  time_s=$(( $(date +%s) - start_s ))

  passed=$(grep -oE '[0-9]+ passed'  "$out" | grep -oE '^[0-9]+' | tail -1)
  failed=$(grep -oE '[0-9]+ failed'  "$out" | grep -oE '^[0-9]+' | tail -1)
  errored=$(grep -oE '[0-9]+ error'  "$out" | grep -oE '^[0-9]+' | tail -1)
  passed=${passed:-0}; failed=${failed:-0}; errored=${errored:-0}
  total=$((passed + failed + errored))

  if [ "$rc" -ne 0 ]; then
    if [ "$failed" -eq 0 ]; then failed=$total; fi
    if [ "$failed" -eq 0 ]; then failed=1; fi
  fi
  if [ "$failed" -ne 0 ]; then
    overall_fail=1
    echo "FAIL   ${pkg}: ${total} tests (${passed} passed, ${failed} failed) in ${time_s}s"
    tail -n 15 "$out"
  else
    echo "PASS   ${pkg}: ${total} tests in ${time_s}s"
  fi
  rows+=("$(printf '%-18s | %7s | %7s | %6s | %4ss' "$pkg" "$total" "$passed" "$failed" "$time_s")")
  rm -f "$out"
done

echo
echo "=== Summary (package | tests run | passed | failed | time) ==="
for r in "${rows[@]}"; do echo "  $r"; done
echo
echo "Total: $((${#rows[@]})) packages with tests, ${skipped} skipped (no tests)."

if [ "$overall_fail" -eq 0 ]; then
  echo "ALL TESTS PASSED"
  exit 0
else
  echo "TESTS FAILED"
  exit 1
fi
