# Differential harness: original vs. refactored

A sans-IO crate can be driven entirely from outside: no sockets, no clock, no threads. That
makes the strongest refactoring check cheap. Run the original and the refactored crate side
by side on the same random sequence of public calls, and compare every output after every
call. If the two logs ever differ, the refactor changed behaviour, and the harness prints the
case that shows it.

Build it **before the first edit** and rerun it after every step. A harness built at the end
can't tell you which step broke something.

## When to build one

Build one when you restructure state that many code paths write (flags into a phase enum,
scattered writers merged into transitions) and no existing test asserts the full output
sequence of those paths. Skip it for extractions, renames, docs and reordering that the
tests already cover. In that case, run the existing property tests with more cases instead.

## Setup

`<skill>` is the skill's base directory (the folder that holds SKILL.md), and `<base>` is
the base commit you noted in step 1. Pass it explicitly, never `HEAD` after your first
commit, or you'd compare only against your last step.

```sh
python3 <skill>/scripts/difftest_scaffold.py --repo <repo> --package <crate> --out <scratch>/difftest --base <base>
```

The script:
- **Copies the original.** It puts the whole repo at `--base` in `<out>/orig` and renames
  every package that lives in the repo to `<name>-orig`: workspace members, and vendored path
  dependencies. Two copies of a package with the same name and version can't share a
  lockfile. Library names stay pinned, so `module_path!()` is unchanged, but
  `CARGO_PKG_NAME` isn't. If a mismatch differs only in the package name (`foo` vs.
  `foo-orig`), normalize it in the driver.
- **Creates the harness crate.** `<out>/harness` is a detached bin crate (an empty
  `[workspace]` table) with two renamed path dependencies: `orig` (the base) and `new` (the
  working tree, not a copy, so it always tests what you are about to commit). It forwards
  every feature to both, copies the repo's `Cargo.lock` so dependency versions match, and
  turns on overflow checks and debug assertions in release builds.
- **Writes `src/main.rs` from a template.** The template has an RNG, a `Case`/`Op` model and
  a `driver!` macro that instantiates the same driving code over `orig` and `new`. It also
  compares the two logs, reports the first mismatch, and counts outcomes.

The harness lives outside the repo, so it never appears in the diff. Delete it at the end, or
leave it in scratch.

Fill in the template's TODOs:
1. **`Op`.** One variant per public input, holding plain data only (bytes, a source index,
   a duration). Generate each op once and feed it to both sides, so the inputs are identical
   even though the two crates' types are distinct.
2. **`Case`.** The configuration as plain data, built into each crate's own `Config` inside
   the driver.
3. **`generate`.** See "What makes a good harness" below.
4. **`driver!`.** Build the machine, apply each op, then drain *every* output after every
   call: each `poll_*` (transmits, events, writes, `take_*` style accessors), and
   `poll_timeout`, rendered relative to the start instant. Use `{:?}` strings, so the two
   sides' different types compare. Check first that `Debug` shows everything that matters: a
   `Debug` that leaves out a field leaves a blind spot.

Run it with `cargo run --release -- <cases> [seed]`, once per feature set CI uses
(`--features ...` or `--all-features`). Pick a case count that runs in under a minute per
feature set: often 10,000–100,000 for a plaintext protocol, far fewer when each case runs a
handshake. At the end, raise it until the coverage counts stop changing.

A panic counts as an output. The template records it, and the case continues to the
comparison. The same panic on both sides is a quirk to list in the summary. A panic on only
one side is a mismatch.

## Make both sides deterministic

Before filling in `generate`, find every source of nondeterminism in the crate:
- an RNG the crate seeds itself, or `rand::random`/`thread_rng`
- `HashMap`/`HashSet` with the default hasher
- `Instant::now` or `SystemTime` (a sans-IO core shouldn't have them, but check)

Feed both sides the same seed through the crate's own hook, such as a seed in the config or
an injected RNG. If there is no hook, normalize what the outputs carry: rewrite random IDs
to their order of first appearance, or sort output kinds whose order is a hash-map
artifact. List each normalization under Verification, because each one is a blind spot.

## Encrypted or handshake-heavy protocols

When valid input can only come from a real peer (TLS, QUIC, DTLS), a harness gets expensive
fast. Cover such a path only if your refactor restructures it, and the crate is mainly that
protocol. If the encrypted path is a side branch that you only moved into a helper, leave it
to its existing tests and name the gap in the summary.

When you do cover it, generate the traffic by running a second instance, or the crate's own
test-pair helper, as the peer. Mutate at the datagram level (drop, duplicate, reorder, delay,
truncate) instead of corrupting bytes. Expect thousands of cases rather than a hundred
thousand.

## What makes a good harness

Good harnesses have these in common:

- **Mostly valid traffic, then mutated.** Random bytes alone never get past the parser.
  Generate plausible protocol messages (the reply the machine waits for, the next sequence
  number, the right peer), then corrupt some: wrong source address or ID, a stale or
  duplicated message, truncation, an extra trailing byte, random junk now and then.
- **Boundary lengths.** 0, 1, max, max + 1 for every length field and buffer size, and
  sizes on either side of a block or payload limit.
- **Degenerate configs.** Zero durations, zero retries, out-of-range sizes, and options left
  out as well as given.
- **Hostile time.** Time that stands still, steps exactly to the deadline, stops just short
  of it (deadline minus 1 ms), and jumps far past it. If the API doesn't forbid it, time
  should sometimes go backwards. Call `handle_timeout` early as well as on time.
- **Stream chunking.** For byte streams, split one coherent server stream into random 1–6
  byte chunks, including one byte at a time.
- **A few very long cases.** About 1 in 100–500 cases should run long enough for counters
  and sequence numbers to wrap. Short cases never reach wraparound.
- **Proof that it can fail.** Before trusting a green run, plant one one-line mutant in the
  working tree, on a path you'll change, and check that the harness reports it. Then revert
  it. Good mutants: flip a `>=` to `>` on a deadline, drop a resend, change a retry count by
  one. Add a second mutant only if the first was caught by something other than the output
  you care about, for example if only the timeout line differed.
- **Coverage, measured.** The template counts each kind of output. Report what was reached
  in the summary's Verification section, and name what wasn't. Take these claims from the
  counters, not from a hand-picked keyword list.

## What it doesn't replace

The harness is throwaway. If it turns up a behaviour worth pinning (a path no test reached,
a quirk you kept on purpose), add a characterization test for it in a new test file. It also
can't see private state: if the `Debug` output of a type is part of a snapshot, or a log
line prints it, check that separately.
