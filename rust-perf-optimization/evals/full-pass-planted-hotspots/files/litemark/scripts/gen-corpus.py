#!/usr/bin/env python3
"""Writes the benchmark corpus (about 3 MB of documentation-like text) to standard output."""
import random

WORDS = """the of and a to in is you that it he was for on are as with his they at be this have
from or one had by word but not what all were we when your can said there use an each which she
do how their if will up other about out many then them these so some her would make like him into
time has look two more write go see number no way could people my than first water been call who
oil its now find long down day did get come made may part parser buffer token stream render index
cache thread value result error option string vector module function library version release""".split()

rng = random.Random(20240611)


def words(lo, hi):
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(lo, hi)))


def sentence():
    parts = [words(6, 16)]
    roll = rng.random()
    if roll < 0.10:
        parts.append("*" + words(1, 3) + "*")
    elif roll < 0.18:
        parts.append("`" + rng.choice(WORDS) + "_" + rng.choice(WORDS) + "()`")
    elif roll < 0.23:
        parts.append("[" + words(1, 3) + "](https://example.org/" + rng.choice(WORDS) + "?a=1&b=2)")
    elif roll < 0.26:
        parts.append("a < b & c > d")
    parts.append(words(3, 10))
    return " ".join(parts).capitalize() + "."


def paragraph():
    lines = []
    for _ in range(rng.randint(2, 6)):
        lines.append(" ".join(sentence() for _ in range(rng.randint(1, 2))))
    return "\n".join(lines)


out = []
size = 0
section = 0
while size < 3_000_000:
    if section % 9 == 0:
        block = "# " + words(2, 5).title()
    else:
        block = paragraph()
    section += 1
    out.append(block)
    size += len(block) + 2
print("\n\n".join(out))
