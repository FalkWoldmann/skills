#!/bin/sh
# Count instructions and hash the output of one binary over a list of cases.
#
#   cg-measure.sh <binary> <cases-file> [workdir]
#
# The cases file has one case per line: the arguments to pass to the binary.
# Empty lines and lines starting with # are skipped. Arguments are split on
# whitespace, so paths with spaces are not supported.
#
# Prints one line per case: <case>|<instructions>|<first 16 hex of sha256(stdout)>
# The binary runs twice per case: once under callgrind, once natively for the hash.
# Needs valgrind. Instruction counts are deterministic, so machine load does not matter.
set -eu

if [ $# -lt 2 ]; then
    echo "usage: $0 <binary> <cases-file> [workdir]" >&2
    exit 2
fi

bin=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
cases=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")
[ $# -ge 3 ] && cd "$3"

command -v valgrind >/dev/null || { echo "valgrind not found" >&2; exit 2; }
if command -v sha256sum >/dev/null; then
    hash() { sha256sum | cut -c1-16; }
else
    hash() { shasum -a 256 | cut -c1-16; }
fi

status=0
while IFS= read -r line || [ -n "$line" ]; do
    case $line in '' | '#'*) continue ;; esac
    # shellcheck disable=SC2086
    set -- $line
    count=$(valgrind --tool=callgrind --callgrind-out-file=/dev/null "$bin" "$@" 2>&1 >/dev/null |
        sed -n 's/.*Collected : \([0-9]*\).*/\1/p')
    if [ -z "$count" ]; then
        echo "no instruction count for case: $line" >&2
        count=0
        status=1
    fi
    sum=$("$bin" "$@" </dev/null | hash)
    echo "$line|$count|$sum"
done <"$cases"
exit $status
