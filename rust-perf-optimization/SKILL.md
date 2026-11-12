---
name: rust-perf-optimization
description: 'Use this skill for any performance work on a Rust crate or binary: "make this faster", "optimize X", "why is this slow", "profile this", "find hot paths", "reduce allocations", "is this change actually faster", "would crate Y or SIMD speed this up", or a request for a performance pass, audit or review of a library, parser, encoder, template engine, CLI, network client, server or async runtime. It runs a measured workflow: find the project''s own benchmark and rules, record a baseline with deterministic instruction counts and output hashes, profile down to source lines and allocation sites, prototype one candidate at a time, try to refute each win with adversarial inputs, confirm on wall-clock time or, for clients and servers, on a load harness (throughput, CPU per unit of work, latency), and report gains, costs and negative results in one table. Use it even for a quick A/B question, because it carries the pitfalls that make benchmark numbers wrong. Not for compile-time or binary-size work, for correctness bugs, or for tuning a deployed system (database settings, autoscaling, network).'
---

# Measured performance work on Rust crates

A performance claim is a measurement. "This should be faster" is a guess until two binaries
have run on the same input and one needed less. Your job is to find where the time goes, try
changes one at a time, keep the ones that survive an honest attempt to refute them, and tell
the user what each one gains, what it costs, and what you did not measure.

Most first ideas do not hold up. Expect half of the candidates to come out neutral, slower on
some input, or subtly wrong, and treat those results as part of the deliverable: a measured
"this does not help" saves the next person the same afternoon.

`<skill>` below means this skill's base directory, the folder that holds this SKILL.md.

## Ground rules

- Numbers before opinions. Don't recommend or keep a change without a before and after from
  the same input, and say which metric each number is (instructions, time, allocations).
- Behaviour stays identical. Same output bytes for every input and option combination, same
  errors, same public API, same MSRV. A faster parser that drops a footnote in one corner case
  is a bug report, and it took a verifier to find that corner case here once: seven output
  hashes and three test runs all passed.
- One change per measurement. Every prototype is measured alone against the same baseline, so
  a number belongs to one idea. Measure the combination separately at the end.
- Follow the project. Before anything else read its contributor docs (CONTRIBUTING, README,
  AGENTS.md or CLAUDE.md, `.github`), and look for a policy on machine-written contributions.
  If the project does not accept them, work in measurement mode: prototypes are throwaway
  evidence, and what you hand over are findings, numbers and plain explanations of the code so
  the user can write the change themselves. Say so as soon as you find the policy, not after
  the patch exists.
- Prototypes are throwaway. Keep them out of the user's history: no commits or pushes unless
  the user asks, and nothing upstream without an explicit request.
- No new dependencies, no `unsafe`, no nightly-only or newer-than-MSRV APIs unless the user
  agrees. A crate the project already depends on is fair game.

## Size the work to the question

Match the effort to what was asked. A quick question should get an answer in a few minutes.

- "Is this patch or version faster, can I merge it?" Build both, measure the main input and
  two guards, read the diff for behaviour, and compare the two binaries on a few thousand
  random inputs. That is steps 3, 6 and the diff and random-input parts of 7. No profiling, no
  further prototypes.
- "Would crate X or technique Y help?" Take one profile and answer from it: name the cost the
  crate would remove, or say that the profile has no such cost and what it shows instead.
  Prototype only when the user asks for an implementation.
- "Make it faster", a performance pass, an audit: all steps.

Fan out to several agents only when the user asked for that scale (see the last section).

For a client, a server or a runtime, where speed shows up as throughput or latency against
another process, read [references/services.md](references/services.md) first. The steps stay
the same, but most of the measuring moves from instruction counts to a load harness.

## Steps

### 1. Orient

Find out, before touching code:

- the project's own benchmarks (`benches/`, a `bench` target in a Makefile, hyperfine
  scripts) and what CI measures. CodSpeed in instruction-count mode, criterion and divan each
  answer a different question, and the maintainer will look at theirs.
- the build profile the benchmarks use (`[profile.release]`, `[profile.bench]`, LTO,
  `codegen-units`), so your binaries match. For an application, the profile is itself a
  candidate: LTO, `codegen-units = 1`, the allocator and `target-cpu` can be worth more than
  any code change. For a library they are its users' choice, so they go in the report as
  suggestions.
- what `cargo clippy` says. Its perf lints are the cheapest findings there are, and it is
  awkward to present a hand-found one that the linter already reports.
- recent performance work: `git log` and the tracker for "perf", "speed", "alloc". Maintainers
  often chose a slower-looking design on purpose (a box to keep a struct small, an exact-size
  copy to save memory). `git log -S'<identifier>'` on a suspicious line usually finds the
  reason, and it saves proposing the reverse of last month's commit.
- for a project the user does not own: open issues and PRs that already cover the hot spot.

### 2. Pick the workload

Use the project's benchmark input as the input that matters most. It is realistic, and it is
the number a reviewer will reproduce.

Then add guard inputs: two or three small synthetic files that are the worst case for the
kind of change you expect to make. A SIMD search wins on long plain runs and loses when a match
comes every few bytes, so a "dense" input belongs in the set from the start. Add a guard
whenever a candidate suggests a new worst case. Guards exist to catch regressions, so keep
them out of headline numbers.

Cover the option combinations that change the hot path (default, the common preset, everything
on). Write the cases to a file, one argument list per line, for the scripts below.

### 3. Build the harness and record the baseline

You need one executable per variant that runs the workload once and writes its output: the
project's CLI, an example, or a few lines of `main`. Then:

```sh
<skill>/scripts/cg-measure.sh path/to/baseline-binary cases.txt > baseline.txt
```

This records, per case, the instruction count under callgrind and a hash of the output.
Instruction counts are deterministic, so they work on a loaded laptop, inside a VM and in
parallel with other builds, which is where most optimisation work happens. Read
[references/measuring.md](references/measuring.md) before the first measurement: it has the
setup, the build flags for line-level profiles, and the pitfalls below in detail.

Check the harness before trusting it:

- What does it do besides the library call? A CLI may turn on syntax highlighting by default
  or validate 11 MB of UTF-8 while reading the file. Constant overhead dilutes every
  percentage, so switch it off or name it.
- Are the absolute numbers plausible? A benchmark that parses megabytes in nanoseconds read an
  empty input, usually through a relative path from the wrong directory.
- Is the baseline the commit you think it is? Record the commit hash next to the numbers, and
  check it again in every fresh worktree. Check `git status` too: a hash says nothing about a
  prototype that is still applied.
- Do different cases give different counts? Identical counts for every case mean the harness
  never reached the workload (a panic on bad arguments, an empty input).

Keep the baseline binary. Every later comparison uses it.

### 4. Profile

Take a line-level instruction profile and an allocation profile of the baseline on the main
workload (commands in the reference). Read the inclusive listing first to see which phases
cost what, then the self costs, then the annotated lines of the top functions. Write down the
harness overhead you found so nobody chases it. When the function names look wrong (a small
callee holding half of all self cost, an inclusive listing that never finishes), calls through
`dyn` are probably tail calls; `<skill>/scripts/cg-lines.py` sums the profile by source line
instead, which stays exact.

For allocations, `<skill>/scripts/dhat-top.py dhat.json` lists the sites by count and by
bytes. The allocator's share of instructions tells you the ceiling for allocation work.

### 5. List candidates with evidence

For each idea write down the function and lines, the instructions or allocations it accounts
for, the change, and an honest expected gain. An idea without a profile number behind it goes
to the bottom of the list. Two references help here:

- [references/patterns.md](references/patterns.md): shapes that paid off in practice, each
  with the condition under which it loses.
- [references/perf-book.md](references/perf-book.md): a checklist condensed from The Rust
  Performance Book, by area (allocations, hashing, type sizes, iterators, inlining, bounds
  checks, I/O, build settings). Read the sections for the areas the profile says are hot.

Ask the big question before the small ones: is this code doing work it could skip, or doing
it more often than needed? A better algorithm, a cheaper data structure or one call instead of
many beats any amount of tuning inside the loop.

Sort by expected gain, merge ideas that touch the same lines, and drop what is below the noise
you can measure (around 0.3% for instruction counts). When a library or crate is suggested as
a fix ("would zerocopy help?"), answer from the profile: name the cost it would remove, or say
that the profile has no such cost.

### 6. Prototype and measure, one at a time

For each candidate: make the smallest change that tests the idea, build with the project's
release profile and one codegen unit (with 16, unrelated edits move counts by percents; the
reference has the numbers), and compare.

```sh
<skill>/scripts/cg-measure.sh path/to/variant-binary cases.txt > variant.txt
<skill>/scripts/cg-compare.py baseline.txt variant.txt
```

The comparison prints the change per case and fails when an output hash differs. If hashes
match, run the test suite. Then look at the guards: a win on the main input with a loss on a
guard is a trade for the user to decide, so report both.

Try a second form when the first result suggests one, and keep the numbers of every form you
tried. Before a large refactor, measure its ceiling with a crude stand-in (hand out objects
from a leaked chunk to see what removing a malloc is worth). Be suspicious of stand-ins that
change more than the thing under test: a pool that survives across benchmark iterations
changes heap layout and can show a slowdown the real design would not have.

Save each prototype as a patch outside the repository and restore the tree before the next
one. When several prototypes build in parallel, give each its own worktree and its own
`CARGO_TARGET_DIR`, or they will overwrite each other's binaries.

### 7. Try to refute each win

A gain is confirmed when someone who wanted it to be wrong could not break it. For every
prototype that helps:

- rebuild from the saved patch and measure again, starting from a clean checkout;
- read the diff for behaviour: empty input, the last byte of the input, CRLF, tabs, non-ASCII,
  very long lines, deep nesting, every option that reaches the changed code;
- construct the input that should hurt most (the fast path's check fails every time, the new
  table overflows, the candidate the search finds is always rejected) and measure it;
- compare outputs against the baseline binary on generated inputs, a few thousand small random
  documents built from the syntax the change touches. Matching hashes on the benchmark files
  plus a green test suite have let real behaviour changes through;
- when the change touches buffering, I/O or error handling, drive the error paths too: a
  writer that fails after N bytes (once accepting partial writes, once not), a value that
  fails halfway through. That found the only behaviour change in a buffering patch whose
  outputs matched everywhere else;
- run the tests the way CI does (default, all features, no default features) and the lints on
  the MSRV toolchain. When some fail, run the same tests on the clean baseline built the same
  way before blaming the change: snapshot and UI tests often embed paths that a target
  directory outside the workspace changes;
- ask what happens on targets without the fast instruction set (wasm without SIMD, older x86)
  when the change relies on one, and say so if you cannot measure it.

Mark each result confirmed, refuted or inconclusive, and keep the reason.

### 8. Confirm on wall-clock time

Instruction counts rank changes well, but a SIMD instruction and a branch do not cost the
same, so confirm the survivors with time on real hardware. Use the quietest machine available,
alternate the binaries over several rounds and compare medians:

```sh
<skill>/scripts/ab-time.py --rounds 5 --runs 20 base='./base in.md' new='./new in.md'
```

If the user has a dedicated benchmark machine, use it rather than a laptop or a VM that shares
cores with other builds, and keep your own measurements off it while it times. On x86, code
layout alone can move a result by a few percent, so for a small difference time a second build
of the same change before calling it.

For benchmark-framework binaries (divan, criterion) alternate whole runs of each binary the
same way. Check the machine's load before and after, and throw away rounds that disagree with
the rest. If no quiet machine is available, report instruction counts only and say that no
time was measured. A noisy timing is worse than none, because it looks like evidence.

### 9. Measure the combination and report

Apply the confirmed prototypes together, measure once more, and check that the output is still
identical. Gains in different code usually add up, but the sum is a prediction until it is
measured.

### 10. Clean up

Remove worktrees, per-variant target directories and scratch inputs, restore the working tree,
and undo anything you changed on a benchmark machine (power profile, sleep inhibitors). Leave
the patches and the result files where the user can find them, and say where.

## The report

Lead with the answer, then one table with a row per idea. When a second form replaced the
first, give one row for the idea with the final form's numbers and mention the earlier form in
the notes below. Ideas that were measured and dropped stay in the table, because a reader
would otherwise try them again:

```markdown
| Finding | Main workload | Guards | Verdict |
|---|---|---|---|
| Skip opener checks when the first byte cannot start a block | −7.0% instr, time not measured | flat | confirmed |
| Smaller backtick table per block | −0.5% instr | +50% on many run lengths | confirmed gain, not worth the worst case |
| Fold lone punctuation into the text run | −1.5% instr | n/a | refuted: loses a footnote after `!` |
```

After the table: the combined number, what was not measured (time, a target, an option
combination), what would change public types or needs a design decision and so belongs in an
issue, and where the patches are. Give instructions and time as separate numbers and name the
machine the times came from.

For each change that is kept, the reader should find three numbers without opening a file:
the count or time before, the count or time after, and the effect on the worst input you
found for it. A percentage alone hides whether the base was the original code or an earlier
step.

When the project wants human-written code, add for each confirmed finding a short explanation
in prose: what the existing code does, why it costs what it costs, and what the idea is. Do
not paste the patch as the thing to submit.

## Working with several agents

When the user asked for a multi-agent run, the steps map onto a pipeline: finders that each
read the profile from one side (per subsystem, plus one for allocations), a ranker that merges
duplicates and drops what the source contradicts, one prototyper per candidate, and one
verifier per win whose brief is to refute it. Do steps 1 to 4 yourself first and hand every
agent the baseline file, the cases file, the profile location and the ground rules.

Things that went wrong in practice: agents sharing one target directory, a worktree created
from the default branch instead of the commit under test, and a build disk filling up when
ten release builds ran at once. Give each agent its own target directory, tell it to verify
its base commit, and have it delete its build output when done.
