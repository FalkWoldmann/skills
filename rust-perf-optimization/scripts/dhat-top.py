#!/usr/bin/env python3
"""List the top allocation sites of a DHAT profile.

    dhat-top.py dhat.json [N]

The profile comes from `valgrind --tool=dhat --dhat-out-file=dhat.json <binary> <args>`.
Prints the N sites (default 15) with the most allocations and the N with the most
bytes. Each row shows the share of all blocks and bytes, the average block size,
the innermost frame, and the first frames outside the allocator and std, which is
usually where the allocation is asked for. Inlining can attribute a site to its
caller, so read the function names as "in or below".
"""
import json
import re
import sys

NOISE = re.compile(
    r"alloc::|__rust|__rdl|malloc|realloc|calloc|core::|std::|\[root\]"
    r"|smallvec|typed_arena|hashbrown|bumpalo"
)


def name(frame):
    frame = re.sub(r"^0x[0-9A-Fa-f]+: ", "", frame)
    frame = re.sub(r" \(in [^)]*\)$", "", frame)
    frame = re.sub(r" \([^()]*:\d+(:\d+)?\)$", "", frame)
    return re.sub(r"::h[0-9a-f]{16}$", "", frame)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    with open(sys.argv[1]) as f:
        prof = json.load(f)
    frames, sites = prof["ftbl"], prof["pps"]
    blocks = sum(p["tbk"] for p in sites) or 1
    size = sum(p["tb"] for p in sites) or 1
    print(f"{blocks:,} allocations, {size:,} bytes in total")

    def row(p):
        stack = [name(frames[i]) for i in p["fs"]]
        own = [f for f in stack if not NOISE.search(f)][:3]
        return "%5.1f%% blocks %5.1f%% bytes  avg %8d  %s" % (
            100 * p["tbk"] / blocks,
            100 * p["tb"] / size,
            p["tb"] // max(p["tbk"], 1),
            " <- ".join(f[-60:] for f in own) or (stack[1][-60:] if len(stack) > 1 else "?"),
        )

    print("\nby number of allocations")
    for p in sorted(sites, key=lambda p: -p["tbk"])[:top]:
        print(row(p))
    print("\nby bytes")
    for p in sorted(sites, key=lambda p: -p["tb"])[:top]:
        print(row(p))


if __name__ == "__main__":
    main()
