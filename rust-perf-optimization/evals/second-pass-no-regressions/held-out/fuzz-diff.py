#!/usr/bin/env python3
"""Differential test: random small documents through two litemark binaries, outputs must match.

    fuzz-diff.py <base-binary> <new-binary> [count] [seed]
"""
import random, subprocess, sys

base, new = sys.argv[1], sys.argv[2]
count = int(sys.argv[3]) if len(sys.argv) > 3 else 5000
rng = random.Random(int(sys.argv[4]) if len(sys.argv) > 4 else 1)

ATOMS = (
    ["*", "`", "[", "]", "(", ")", "\\", "](", "# ", "#", "\n", "\n", "\r\n", "\r", "\n\n", "\r\n\r\n",
     " ", " ", "\t", "&", "<", ">", '"', "-", "a", "b", "Z", "9", "é", "☕", " ", " ",
     "İ", "ß", "Ǆ", "　", "\x0b", "\x0c", "word", "a long run of plain text here",
     "[t](u)", "*e*", "`c`", "\\*", "\\[", "\\\\", "\\a", "[a\nb](u)", "[a](u v)", "[](u)", "[a]()",
     "**", "``", "# Title", "# Title\n\n# title", "  \n", " \r\n", "x" * 20, '"' * 3 + "&" * 17]
)


def doc():
    style = rng.randrange(4)
    n = rng.randint(0, 6) if style == 0 else rng.randint(1, 60)
    atoms = ATOMS if style != 2 else ["[", "]", "(", ")", "](", "\n", "a", " ", "*", "`", "\\"]
    if style == 3:
        atoms = ["&", "<", ">", '"', "a", "é", "x" * 15, "x" * 16, "x" * 17, "*", "`", " "]
    return "".join(rng.choice(atoms) for _ in range(n))


def run(binary, text):
    p = subprocess.run([binary], input=text.encode(), capture_output=True)
    return p.returncode, p.stdout, p.stderr


bad = 0
for k in range(count):
    text = doc()
    a, b = run(base, text), run(new, text)
    if a != b:
        bad += 1
        print("MISMATCH", repr(text), a, b, sep="\n  ")
        if bad >= 5:
            break
print(f"{count} documents, {bad} mismatches")
sys.exit(1 if bad else 0)
