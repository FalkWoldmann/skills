#!/usr/bin/env python3
"""Writes the guard inputs for the litemark perf pass into the directory given as argv[1]."""
import random, sys, os
d = sys.argv[1]
corpus = open(sys.argv[2], encoding="utf-8").read()
rng = random.Random(7)
W = "alpha beta gamma delta naïve café ☕ x y zz".split()

def w(n): return " ".join(rng.choice(W) for _ in range(n))

def put(name, text):
    with open(os.path.join(d, name), "w", encoding="utf-8", newline="") as f:
        f.write(text)

# a special byte every few bytes
parts = []
for _ in range(60000):
    r = rng.randrange(8)
    parts.append(["*%s*" % w(1), "`%s`" % w(1), "[%s](u%d)" % (w(1), r), "\\*", "\\[", "a\\b", "2 * 3", w(1)][r])
    parts.append(rng.choice([" ", " ", " ", "\n", "\n\n"]))
put("dense.txt", "".join(parts))

# text that is mostly characters to escape
put("escapes.txt", "\n\n".join(" ".join(rng.choice(['&', '<', '>', '"', 'a<b', '&amp;', 'x', '<<>>', 'é&']) for _ in range(40)) for _ in range(8000)))

# headings only, many duplicates, non-ASCII and punctuation
put("headings.txt", "\n\n".join("# " + rng.choice(["Hello, World", "ÄÖÜ ẞ İstanbul", "a--b  c", "*emph* `code`", "  ", "x", w(4)]) for _ in range(40000)))

# the corpus with CRLF line endings
put("crlf.txt", corpus[:1000000].replace("\n", "\r\n"))

# one-line blocks of a few words
put("short.txt", "\n\n".join(w(rng.randint(1, 4)) for _ in range(80000)))

# unclosed brackets in one block: every `[` searches for `](`
put("brackets.txt", "\n".join("[" + w(2) + " [x] [" for _ in range(3000)) + "\n\n" + "[a\nb](u) " * 2000)

# one very long paragraph without specials
put("plain.txt", w(200000))
