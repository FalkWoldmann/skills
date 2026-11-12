# Patterns that tend to pay, and when they do not

Each entry says what to look for in the profile, the change, and the condition under which it
loses. Use it to form candidates in step 5. The profile decides, not this list.

## Byte-at-a-time scans over long runs

Look for: a loop that tests each byte against a table or a `match` and usually runs for dozens
of bytes before it finds one (`find the next special character`, `find the end of the line`).

Change: search with `memchr` or a multi-byte searcher the project already depends on, and keep
the per-candidate check that existed before.

Loses when: matches are a few bytes apart (set-up per call costs more than the bytes skipped),
when the loop usually runs for zero or one byte (a table lookup is already optimal), when the
scan goes backwards, and on targets without SIMD, where the fallback can be slower than the
table. Things measured as worse than the plain "search, check, search again" loop: an
iterator that precomputes matches in batches and is dropped after the first hit, and a scalar
prefix before the SIMD search.

Guard input: text with a candidate every few bytes, and short lines.

Without a search crate or SIMD (a crate with no dependencies, or a small fixed set of bytes),
test eight bytes at a time as a `u64`: `(v - 0x01..01) & !v & 0x80..80` on `v ^ splat(c)` flags
the bytes equal to `c`, and `v | splat(0x01)` folds two neighbouring bytes into one test. Walk
the flagged bytes with `trailing_zeros` instead of rescanning a dirty word byte by byte. Only
the lowest flag is certain; the ones above it can be false positives from the borrow, so check
each one with the old per-byte test. In a template engine's HTML escaper this halved the
instructions on prose and made dense markup 9% cheaper, where an earlier form (test a 16-byte
block, then rescan the whole block byte by byte) had made dense markup 6 to 15% slower. Keep
the old loop for short strings and put the word loop in its own `#[inline(never)]` function:
with both in one function the larger prologue made 1 to 2 byte strings slower, +2.5% and +4.5%
on a benchmark of small numbers, and with the split they pay two instructions for the length
check. Guards: input made only of matching bytes (+4% instructions, +8% time there), and, when
a candidate byte can also be part of a multi-byte character (`0xA9` ends U+2029 and is the
second byte of `é`), text full of those characters.

## A chain of checks that almost always fails

Look for: a dispatcher that tries a dozen recognisers in order on every line or token, where
most inputs match none (`does this line open a heading, a list, a fence, a table ...`).

Change: test one cheap necessary condition first (the first non-space byte is in the set of
bytes that can start anything) and skip the chain when it fails.

Loses when: the set drifts out of sync with the recognisers, which is a correctness risk.
Derive the set from reading every recogniser, test it against a mutant (remove one byte, a
test must fail), and tell the user that a new recogniser has to extend the set.

## Generated or regex scanners used for a literal search

Look for: a state machine (re2c, a regex, a hand-rolled DFA) whose pattern is "any bytes, then
a literal", costing tens of instructions per byte.

Change: a substring or byte search with the same stop conditions (for example, stop at the
first newline).

Loses when: the pattern is more than a literal after all. Write the predicate down in words
and compare outputs on random inputs. Generated files usually have a source file that must
change with them.

## Many small writes through `fmt`

Look for: output code that issues several `write_str` or `write!` calls per element for what
is a constant string in the common case (`<p>`, `</code></pre>\n`), or builds an attribute
list that is empty most of the time.

Change: one write of a static string on the fast path, with the general path unchanged behind
a check.

Loses when: the fast-path check fails most of the time for some option (source positions,
custom attributes): measure that option too. The cost is a few instructions per element.

## Unbuffered writes to an `io::Write`

Look for: an adapter that turns `fmt::Write` calls into `io::Write::write_all` one fragment at
a time. On a `File`, a socket or a pipe each fragment is a syscall; `strace -c -e trace=write`
counts them, callgrind does not see their cost.

Change: a small stack buffer in the adapter, flushed when full, at the end and on errors. In a
template engine a 1 KiB buffer took a page from 30,202 `write(2)` calls to 108 (about ten
times faster), and even writing into a `Vec<u8>` got 17% cheaper, because the buffer removes
the second dynamic call per fragment.

Loses when: the buffer is big enough that zeroing it shows on small outputs (8 KiB cost a
small page 3.6%), and on error paths: a writer that rejects a whole write receives a different
prefix before the error. Test the error paths with their own random inputs (a writer that
fails after N bytes, once accepting partial writes and once not); output hashes on normal
inputs cannot see this.

## Cheap pre-checks before expensive per-node work

Look for: a function that runs on every text node and does set-up (selecting a matcher,
building a struct) before it finds out that the node has nothing for it.

Change: test the precondition first with the fastest available search, and move the rest into
a separate function that is not inlined.

Loses when: the precondition is nearly always true.

## Allocation per element

Look for: an allocation site whose count equals the number of nodes, lines or tokens.

Change, in rising order of effort: borrow a static string for constant content, reuse a buffer
owned by the parser, reserve capacity once, store small things inline, keep per-element data
in storage owned by the parser and index into it.

Loses when: the box or the exact-size copy was a deliberate memory trade (check the history),
when the type is public, or when the saving is below a few percent and the change touches
dozens of call sites. Measure the ceiling first with a crude stand-in.

A common case in output code: a conversion that allocates per call, such as `to_lowercase()`
once per word in a title-case filter. When the input is ASCII the result is known without
context, so write unchanged runs straight through and convert the rest in a small stack chunk,
keeping the allocating path for everything else (`str::to_lowercase` has a final-sigma rule
that a byte-wise conversion would get wrong). That took a filter-heavy page down 19%. Guard:
input where every byte changes (all caps), and non-ASCII input that must take the old path.

## Capacity guesses that just miss

Look for: an output buffer whose initial capacity comes from a heuristic a little below the
usual output size, so every call reallocates exactly once. The allocator's share in a small
case gives it away.

Change: measure the ceiling with a crude stand-in first (reserve twice the guess). In a
template engine one realloc per render was 18% of a small page's instructions and 25% of its
time with glibc.

Loses when: memory per call matters more than the realloc, and the number depends on the
allocator. Usually this is a heuristic the maintainers own, so report the ceiling as a
question rather than sending a patch that doubles everyone's buffers.

## Per-call set-up of large state

Look for: a constructor that zeroes hundreds of bytes or builds a table for every block,
message or request, most of which is never read.

Change: a small inline vector of the entries in use, lazy initialisation, or one instance
reused across calls.

Loses when: a pathological input uses many entries and the lookup becomes linear. Construct
that input.

## Redundant passes

Look for: the same bytes scanned twice in a row (count newlines, then normalise; find the end,
then copy), or a no-op step executed for every node (an "exit" visit for leaves that render
nothing on exit).

Change: one pass, or skip the step for the kinds that cannot need it.

Loses when: the pre-scan that decides "nothing to do" is itself scalar and the input makes it
run long before failing. Use a vectorised search for the pre-scan above a small length.

## Things that rarely help

- Swapping in a crate because it is fast at something else. A concurrent pointer swap does
  nothing for single-threaded parsing; a zero-copy cast crate does nothing for code that copies
  text into owned strings by design. Name the cost in the profile that the crate would remove.
- Replacing a single-byte table lookup with SIMD.
- Inlining hints and branch hints without a measurement. They move code around, and layout
  shifts alone change counts by a tenth of a percent.
- A different global allocator inside a library. It can be worth several percent, but it is
  the application's decision.
