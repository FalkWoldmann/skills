#!/usr/bin/env python3
"""Self cost per source file or per source line from a callgrind profile.

    cg-lines.py cg.out files [N]          the N most expensive source files
    cg-lines.py cg.out lines [N] [REGEX]  the N most expensive lines, optionally only in
                                          files whose path matches REGEX

It ignores callgrind's function attribution, which tail calls confuse (a call through
`dyn Trait` that compiles to a jump charges the caller's loop to the callee), and sums the
cost lines by the file and line their debug info names, which stays exact. Inlined code is
charged to its own file and line. Needs a build with line tables; source text is shown when
the file exists at the recorded path.
"""
import os
import re
import sys
from collections import defaultdict

NAME = re.compile(r"\((\d+)\)(?: (.*))?")


def parse(path):
    names = {}

    def name(spec):
        m = NAME.match(spec)
        if not m:
            return spec
        if m.group(2) is not None:
            names[m.group(1)] = m.group(2)
        return names.get(m.group(1), spec)

    cost = defaultdict(int)
    total = 0
    fn_file = cur_file = None
    last = 0
    after_calls = False
    with open(path, errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            c = line[0]
            if c.isdigit() or c in "+-*":
                parts = line.split()
                p = parts[0]
                pos = last if p == "*" else last + int(p) if p[0] in "+-" else int(p)
                last = pos
                if after_calls:
                    # the cost line after `calls=` is the callee's inclusive cost
                    after_calls = False
                    continue
                n = int(parts[1]) if len(parts) > 1 else 0
                cost[(cur_file, pos)] += n
                total += n
                continue
            key, _, val = line.partition("=")
            if key == "fl":
                fn_file = cur_file = name(val)
            elif key in ("fi", "fe"):
                cur_file = name(val)
            elif key == "fn":
                cur_file = fn_file
            elif key == "calls":
                after_calls = True
            elif key in ("cfi", "cfl"):
                # file names share one compression table; function and object names have
                # their own, so they must not go into `names`
                name(val)
    return cost, total


def short(path):
    path = path or "?"
    path = re.sub(r".*/lib/rustlib/src/rust/library/", "std:", path)
    path = re.sub(r".*/registry/src/[^/]+/", "crate:", path)
    path = re.sub(r".*/glibc-[^/]+/.*/", "glibc:", path)
    cwd = os.getcwd() + os.sep
    return path[len(cwd):] if path.startswith(cwd) else path


def main():
    if len(sys.argv) < 3 or sys.argv[2] not in ("files", "lines"):
        sys.exit(__doc__)
    cost, total = parse(sys.argv[1])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    print(f"total {total:,}")
    if sys.argv[2] == "files":
        per_file = defaultdict(int)
        for (f, _), v in cost.items():
            per_file[f] += v
        for f, v in sorted(per_file.items(), key=lambda kv: -kv[1])[:n]:
            print(f"{v:>14,} {100 * v / total:6.2f}%  {short(f)}")
        return
    rx = re.compile(sys.argv[4]) if len(sys.argv) > 4 else None
    rows = [kv for kv in cost.items() if not rx or rx.search(kv[0][0] or "")]
    rows.sort(key=lambda kv: -kv[1])
    sources = {}
    for (f, ln), v in rows[:n]:
        text = ""
        if f and os.path.exists(f):
            if f not in sources:
                with open(f, errors="replace") as src:
                    sources[f] = src.read().split("\n")
            if 0 < ln <= len(sources[f]):
                text = sources[f][ln - 1].strip()[:90]
        print(f"{v:>14,} {100 * v / total:6.2f}%  {short(f)}:{ln}  {text}")


if __name__ == "__main__":
    main()
