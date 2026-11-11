#!/usr/bin/env python3
"""Time several commands in alternating rounds and compare medians.

    ab-time.py [--rounds 5] [--runs 20] name='command ...' name='command ...'

Each round runs every command `--runs` times and keeps the median wall time, then
moves to the next command, so a burst of load on the machine hits all variants
alike. The first command is the baseline. A round whose median is more than 3%
off that command's median over all rounds is marked as disturbed: rerun when
several are marked.

Whole-process time includes start-up and I/O, so use inputs that run for at
least a few tens of milliseconds. Standard output and error are discarded.
"""
import argparse
import shlex
import statistics
import subprocess
import time


def run(argv):
    start = time.perf_counter()
    subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return time.perf_counter() - start


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("commands", nargs="+", metavar="name=command")
    args = ap.parse_args()

    commands = []
    for spec in args.commands:
        name, _, command = spec.partition("=")
        if not command:
            ap.error(f"expected name=command, got {spec!r}")
        commands.append((name, shlex.split(command)))

    for _, argv in commands:
        run(argv)  # warm caches, fail early on a bad command

    rounds = {name: [] for name, _ in commands}
    for _ in range(args.rounds):
        for name, argv in commands:
            rounds[name].append(statistics.median(run(argv) for _ in range(args.runs)))

    base = statistics.median(rounds[commands[0][0]])
    print("| Variant | Median | Range over rounds | vs first | Disturbed rounds |")
    print("|---|---|---|---|---|")
    for name, _ in commands:
        meds = rounds[name]
        med = statistics.median(meds)
        off = sum(1 for m in meds if abs(m / med - 1) > 0.03)
        print(
            f"| {name} | {med * 1e3:.2f} ms | {min(meds) * 1e3:.2f} to {max(meds) * 1e3:.2f} ms "
            f"| {100 * (med / base - 1):+.1f}% | {off} of {len(meds)} |"
        )


if __name__ == "__main__":
    main()
