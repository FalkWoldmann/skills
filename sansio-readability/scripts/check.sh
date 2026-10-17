#!/usr/bin/env bash
# The per-step gate for a readability refactor: format check, lint and test
# every feature set, and fail if any of it fails.
#
# usage: check.sh <repo-dir> [feature-set ...]
#   feature-set: "default", "all", "none", or a comma-separated feature list
#   (default: "default all").
# Environment:
#   CHECK_PACKAGES      replaces --workspace, e.g. "-p mycrate -p its-driver"
#   CHECK_CARGO_FLAGS   added to every cargo call, e.g. "--locked"
#   CHECK_CLIPPY_FLAGS  passed after `--` to clippy (default "-D warnings")
#   CHECK_FMT           "check" (default) or "off"; never reformats anything
# Per feature set: clippy --all-targets, then the tests (nextest when installed,
# plus doc tests). Prints one line per check and the tail of each failure's
# log. Exit status is non-zero if anything failed.
set -u
if [ $# -lt 1 ] || [ ! -f "$1/Cargo.toml" ]; then
  echo "usage: check.sh <repo-dir> [feature-set ...]  (no Cargo.toml in '${1:-}')" >&2
  exit 2
fi
repo=$1
shift
sets=("$@")
[ ${#sets[@]} -eq 0 ] && sets=(default all)
cd "$repo" || exit 2
logs=$(mktemp -d)
flags="${CHECK_PACKAGES:---workspace} ${CHECK_CARGO_FLAGS:-}"
clippy_flags=${CHECK_CLIPPY_FLAGS:--D warnings}
failed=0

logfile() { echo "$logs/$(printf %s "$1" | tr -c 'A-Za-z0-9_.,[]-' _).log"; }

# step <name> <skip-pattern|-> <command...>: a log line matching the skip
# pattern turns a failure into a skip (e.g. doc tests without a lib target).
step() {
  local name=$1 skip=$2
  shift 2
  local log
  log=$(logfile "$name")
  if "$@" >"$log" 2>&1; then
    echo "ok   $name"
  elif [ "$skip" != - ] && grep -q "$skip" "$log"; then
    echo "skip $name ($skip)"
  else
    echo "FAIL $name ($*)"
    tail -n 40 "$log" | sed 's/^/     /'
    failed=1
  fi
}

feature_flags() {
  case $1 in
    default) ;;
    all) echo --all-features ;;
    none) echo --no-default-features ;;
    *) echo --features "$1" ;;
  esac
}

if [ "${CHECK_FMT:-check}" != off ]; then
  step fmt - cargo fmt --all --check
fi
have_nextest=0
cargo nextest --version >/dev/null 2>&1 && have_nextest=1
for set in "${sets[@]}"; do
  # shellcheck disable=SC2046,SC2086
  step "clippy[$set]" - cargo clippy $flags --all-targets $(feature_flags "$set") -- $clippy_flags
  if [ $have_nextest = 1 ]; then
    # shellcheck disable=SC2046,SC2086
    step "test[$set]" - cargo nextest run $flags $(feature_flags "$set") --no-tests=pass
    # shellcheck disable=SC2046,SC2086
    step "doctest[$set]" "no library targets found" cargo test $flags --doc $(feature_flags "$set")
  else
    # shellcheck disable=SC2046,SC2086
    step "test[$set]" - cargo test $flags $(feature_flags "$set")
  fi
done
echo "logs: $logs"
exit $failed
