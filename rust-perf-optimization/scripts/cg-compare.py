#!/usr/bin/env python3
"""Compare two result files written by cg-measure.sh.

    cg-compare.py baseline.txt variant.txt

Prints a Markdown table with the instruction count per case, the change in
percent (negative is better) and whether the output hash is the same.
Exits 1 when a hash differs or a case is missing, so it can gate a script.
"""
import sys


def load(path):
    rows = {}
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            case, count, digest = line.rsplit("|", 2)
            rows[case] = (int(count), digest)
    return rows


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    base, new = load(sys.argv[1]), load(sys.argv[2])
    ok = True
    print("| Case | Baseline | Variant | Change | Output |")
    print("|---|---|---|---|---|")
    for case, (b_count, b_hash) in base.items():
        if case not in new:
            print(f"| `{case}` | {b_count:,} | missing | | |")
            ok = False
            continue
        n_count, n_hash = new[case]
        change = f"{100 * (n_count / b_count - 1):+.2f}%" if b_count else "n/a"
        same = "same" if n_hash == b_hash else "DIFFERENT"
        ok = ok and n_hash == b_hash and b_count > 0 and n_count > 0
        print(f"| `{case}` | {b_count:,} | {n_count:,} | {change} | {same} |")
    for case in new.keys() - base.keys():
        print(f"| `{case}` | missing | {new[case][0]:,} | | |")
        ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
