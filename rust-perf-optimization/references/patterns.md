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
