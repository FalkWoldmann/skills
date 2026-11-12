# Measuring

Contents: which metric for what, building variants, instruction counts, line-level profiles,
allocation profiles, wall-clock time, sampling profilers, benchmark-framework binaries, macOS,
async code, build traps, pitfalls.

## Which metric for what

| Metric | Tool | Good for | Blind to |
|---|---|---|---|
| Instructions executed | callgrind | ranking changes, A/B on a noisy machine, per-line cost | cache misses, branch mispredictions, the different cost of SIMD and scalar instructions |
| Allocations | DHAT | finding avoidable mallocs and copies | what an allocation costs in time |
| Wall-clock time | alternating runs on a quiet machine | the number users feel, final confirmation | nothing, but it needs a quiet machine and patience |

Use instruction counts to search and time to confirm. In one parser the same change measured
−10% instructions and −5.9% time: both true, and a report should give both.

Valgrind runs on Linux. On a Mac, run it in a Linux VM or container that mounts the checkout.
A count from an aarch64 VM and a time from an x86-64 machine describe different SIMD code, so
name the architecture next to each number.

## Building variants

Build with the profile the project's benchmarks use. If `[profile.release]` sets `lto` or
`codegen-units = 1`, a plain `cargo build --release` already matches; `cargo bench` uses the
`bench` profile, which inherits from `release`.

Keep one binary per variant under a name that says what it is, and copy it out of the target
directory right after the build, because the next build overwrites it:

```sh
cargo build --release --locked && cp target/release/<bin> ~/perf/<variant>
```

When builds run in parallel (several agents, several worktrees), give each its own
`CARGO_TARGET_DIR`. A shared one makes builds wait for each other and lets one variant pick up
another's binary. Ten cold release builds with LTO can also fill a small disk, so delete each
directory when its measurement is done.

A rebuild of the same source in a different directory can differ by a few hundred
instructions, and occasionally by a percent on a small input, because paths and layout shift.
When a delta is that small, build the baseline in the same directory as the variant and
compare those two.

Codegen units move counts much more than that. With the default 16 per crate, which functions
share a unit, and so what gets inlined where, changes with edits far away from the hot path:
in a template engine, editing one unrelated template moved the main case by 3.1%. With
`CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1` the same edit moved it by 41 instructions. Build every
variant with one codegen unit unless the project's profile already sets it, and say so next to
the numbers, since it is not what the project's own benchmark builds.

Build each variant from a clean tree: apply the saved patch, build, copy the binary out,
restore the tree, and refuse to build when `git status` shows anything. A small script that
does exactly that pays for itself on the second variant. The commit hash next to the numbers
does not catch a prototype that is still applied, which is how one baseline once got built
with a candidate in it.

## Instruction counts

```sh
valgrind --tool=callgrind --callgrind-out-file=/dev/null ./variant <args> > /dev/null
```

The total is on the `Collected :` line of stderr. `scripts/cg-measure.sh` does this for a list
of cases and adds an output hash; `scripts/cg-compare.py` turns two result files into a table.

The count covers the whole process, so everything the harness does is in it. Run the baseline
once with `--callgrind-out-file=cg.out`, look at `callgrind_annotate cg.out | head -40`, and
check that the top entries are library code. Typical surprises: UTF-8 validation of the input
in `main`, a default feature of the CLI (syntax highlighting, colour, config file lookup),
output formatting. Turn them off with flags where possible, and otherwise report "x% of the
run is harness".

When valgrind runs in a VM or container, call the scripts by a path that exists in there.
`<skill>` is often a symlink (from `~/.claude/skills` into a repository, say) that the VM does
not mount; `realpath <skill>` gives the directory it points to, or copy `scripts/` next to the
results.

## Line-level profiles

Function totals come without debug info. For per-line counts the binary needs line tables:

```sh
CARGO_PROFILE_RELEASE_DEBUG=line-tables-only \
CARGO_PROFILE_RELEASE_STRIP=none \
CARGO_PROFILE_RELEASE_SPLIT_DEBUGINFO=off \
  cargo build --release --locked
```

The last two matter when a global cargo config strips release binaries or splits debug info;
check with `readelf -S <bin> | grep debug_line`. Line tables do not change code generation in
a way that matters (a few thousand instructions on hundreds of millions), but use the normal
build for baseline numbers anyway.

```sh
valgrind --tool=callgrind --callgrind-out-file=cg.out ./variant-dbg <args> > /dev/null
callgrind_annotate --inclusive=yes cg.out | head -80     # phases: who costs what in total
callgrind_annotate cg.out > self.txt                     # self cost, then annotated source
```

`self.txt` runs to thousands of lines. Search it for the file or function instead of reading
it whole. Inlined callees are charged to the line that calls them, and a heavily inlined
function can show most of its cost under a caller's name; the annotated source of the callee's
file still shows the per-line numbers.

Tail calls break the function view. A call through `dyn Trait` (a `&mut dyn fmt::Write`, a
boxed callback) often compiles to a jump, and callgrind then charges the caller's loop to the
callee: in a template engine `<String as fmt::Write>::write_str'2` showed half of all self cost,
including the render loop, and `callgrind_annotate --inclusive=yes` ran for minutes on the
cycles without finishing. Line attribution comes from debug info and stays exact, so sum by
source line instead:

```sh
scripts/cg-lines.py cg.out files 20              # cost per source file, inlined code included
scripts/cg-lines.py cg.out lines 40 'src/'       # hottest lines of the crate's own files
```

Call counts (`calls=` records) stay reliable under tail calls, so "how many writes per
element" can still be answered from the profile file.

## Allocation profiles

```sh
valgrind --tool=dhat --dhat-out-file=dhat.json ./variant <args> > /dev/null
scripts/dhat-top.py dhat.json
```

Stderr gives the totals (blocks, bytes, peak). For the ceiling of allocation work, sum the
allocator's functions in the callgrind profile (`malloc`, `free`, `realloc` and the `_int_*`
helpers on glibc). If the allocator is 13% of instructions and a site makes 30% of the
allocations, removing that site is worth at most about 4%, and less once the replacement's own
cost is counted. Other allocators have other costs: the share on macOS or with mimalloc will
differ from glibc's.

Recognise a site by its size. A steady stream of 96-byte blocks from the function that creates
nodes is a boxed struct of 88 bytes; blocks averaging 9 bytes from a string path are tiny
owned strings.

## Wall-clock time

Timing needs a machine that is doing nothing else. Check `uptime` and the top CPU users before
and after; a desktop session, an indexer or a second build makes a 2% effect invisible.

- Alternate variants (A B C, A B C, ...) and compare medians per variant. A background burst
  then lands on all of them.
- Pin to one core (`taskset -c 2 ...` on Linux) and, where you are allowed to, set a fixed
  power profile and hold a sleep inhibitor for the run. Put both back afterwards.
- Do several rounds. If one round shows doubled times, something else ran: keep the medians,
  mention the disturbed round.
- If the medians of the same binary move by more than the effect between rounds, the machine
  is too noisy. Stop and report instruction counts only.
- Keep your own work off the machine while it times. A valgrind run on another core lowers the
  turbo clock of the one being timed, so queue instruction counts after the timing run. When
  someone else uses the machine during a run (a package install, a login), retime the cases
  whose rounds overlapped instead of trusting the disturbed-round flag alone.
- Code layout alone moves time by several percent on x86. Three builds with the same source on
  the hot path and the same instruction count timed −0.1%, +3.4% and +5.6% against one
  baseline. Before reporting a small time difference as a gain or a loss, time a second build
  of the same change (together with an unrelated patch, for example) and give the spread.

`scripts/ab-time.py` does the alternation for whole-process runs. `hyperfine` is a good
general tool for timing commands when it is installed, but it runs each command's samples in
one block, so on a machine that is not quiet prefer alternation.

## Sampling profilers

On Linux `perf record` and on any platform `samply record` show where time goes without
valgrind's slowdown, and they see cache and branch effects that instruction counts miss. A
second profiler is worth the few minutes when the instruction profile and the timings
disagree. If call stacks come out broken, build with `-C force-frame-pointers=yes`. The full
list of profilers is in [perf-book.md](perf-book.md).

## Benchmark-framework binaries

`cargo bench --no-run` prints the path of each bench executable. Copy it per variant, like a
CLI binary, and run the copies alternately. A bench binary run by hand needs the `--bench`
flag, or it exits at once as if it were a test run. Divan takes `--sample-count N` and a name
filter as positional argument; criterion takes a filter and `--measurement-time`.

Benchmarks that read fixtures use paths relative to the current directory. Run the binary
from the directory `cargo bench` would use (the package root), or it measures an empty input
and reports nanoseconds.

A benchmark file with `#![feature(test)]` needs a nightly toolchain to build.

## macOS

Without valgrind, `samply record` and `/usr/bin/sample <pid>` give sampling profiles that show
where time goes, which is enough for step 4. For A/B numbers on a Mac use timing with
alternation, or run callgrind in a Linux VM. Symbolication at line level needs a dSYM, which
a release profile without debug info does not produce.

## Async code

A profile of code on an async runtime needs two adjustments.

The inclusive listing is useless: tasks are polled through the same runtime functions again
and again, callgrind sees that as recursion, and the totals come out at thousands of percent.
Work from self cost, grouped by function and by source file, and from call counts. The call
counts are in the profile file as `calls=` lines under `fn=` and `cfn=` records; a few lines
of Python that sum them per callee answer "how often per record is this called?", which is
usually the question.

Count calls to the clock, the allocator, locks and semaphores per unit of work. `Instant::now`
goes through the vDSO, which callgrind sees as a handful of instructions, while on real
hardware it is 20 ns or more. Seven clock reads per record looked like 1% of instructions and
were worth several percent of CPU time.

Use a current-thread runtime in the driver and a linger or flush interval long enough that
batches close by size, or the valgrind slowdown changes batch boundaries and the counts stop
being repeatable. With that, three runs of a producer agreed to 0.03%.

## Build traps

- A profile section in a global cargo config overrides the same key in a manifest. Set debug
  info and stripping through `CARGO_PROFILE_RELEASE_*` environment variables, which win over
  both, and check the binary with `readelf`.
- An example or bench inside the crate is built with the crate's dev-dependencies, and their
  features are unified into the build. A dev-dependency on `tokio` with `test-util` puts a
  pausable clock into every time call. Build the driver as its own small crate with a path
  dependency, and check `cargo tree -e features -i <crate>`.

## Pitfalls that produced wrong numbers

- A CLI default (syntax highlighting) accounted for 40% of the run, so a 10% gain in the
  parser read as 5%.
- A bench binary started from the wrong directory parsed an empty string in 150 ns. The
  numbers still differed between variants, by the cost of constructing a matcher.
- A box-recycling pool kept across benchmark iterations made the realistic input 14% slower by
  fragmenting the heap, which says nothing about a parser-owned arena.
- Seven identical output hashes and three passing test runs did not notice a lost footnote.
- Medians on a shared VM moved by several percent between rounds while the effect under test
  was 2%.
- A shell loop over the cases passed each case as one argument, because zsh does not split an
  unquoted variable. Every case measured the same 417,000 instructions, the start-up cost of a
  panic. Identical counts for different cases mean the harness did not run.
- A baseline built while a prototype was still applied. It looked fine because its commit hash
  was right; `git status` would have shown it.
