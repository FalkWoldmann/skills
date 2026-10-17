---
name: sansio-readability
description: 'Use this skill for any behaviour-preserving restructuring of a sans-IO Rust protocol core. That means a crate that takes `now: Instant`, is fed input through handle_* calls and drained through poll_transmit/poll_event/poll_timeout, such as quinn-proto, str0m, or a resolver, handshake, framing or client core. Use it when the user wants the state machine made readable or easier to follow, flags untangled into state enums, handlers simplified, code refactored for clarity, or a large file split or reorganized into modules, even if they say "just move code". Short asks like "this resolver.rs is hard to follow" count too. The skill maps the states, inputs, outputs and timers, refactors in small steps checked against the original, keeps the public API and output order identical, and ends with a summary. Not for fixing bugs, adding features, tuning performance, reviewing a PR, writing user-facing docs, or converting async or socket-based code to sans-IO.'
---

# Readable sans-IO state machines

A sans-IO library is a state machine with the I/O pulled out. The caller feeds it inputs
(`handle_*`, each with `now`), drains its outputs (`poll_transmit`, `poll_event`,
`poll_timeout`) and owns the sockets and timers. Code like this is worth having only if people
can reason about it: the next maintainer, the author of a driver, a reviewer checking it
against an RFC. Each of them should be able to answer four questions fast:

1. **States**: which states can each long-lived entity (connection, query, stream, session)
   be in, and which data exists in each?
2. **Transitions**: which inputs move it from one state to another, and where in the code does
   each move happen?
3. **Outputs**: what does each move queue (transmits, events, writes), and in what order?
4. **Time**: when does it need waking up, and which rule sets each deadline?

Your job is to make those answers visible in the types and the code while the machine keeps
doing exactly what it did. You edit the working tree and finish with a summary.

`<skill>` below means this skill's base directory, the folder that holds this SKILL.md.

## Ground rules

- **Behaviour stays identical.** In a sans-IO crate, behaviour covers things that look
  cosmetic:
  - the order in which outputs are queued
  - the iteration order of maps (a `BTreeMap` or an insertion-ordered `Vec` decides who goes
    first)
  - which instant `poll_timeout` returns
  - whether an empty write or a no-op event is emitted at all
  - which error an entity fails or closes with
  - the output of a `#[derive(Debug)]` type whose fields you change, if a snapshot, log
    assertion or error message prints it

  Tests that go through the public API, and every snapshot, must pass unchanged. If one needs
  editing, that step changed behaviour: undo it. Unit tests inside the crate that name private
  items may need the same mechanical edit as the code (a flag that became a variant, a renamed
  helper). Make only that edit, keep what each assertion checks, and list the test in the
  summary.
- **Leave the public API alone.** Keep the names, signatures, variants and fields of `pub`
  items as they are, since drivers and downstream crates depend on them (and on semver).
  `pub(crate)` and private items are fair game. Put API improvements in the summary as
  suggestions. How to check this is in step 5.
- **Don't spend performance on readability.** No new clones, allocations or extra passes over
  the maps on paths that run per input (per packet, message or query). A `mem::replace` or
  `mem::take` is free; cloning a `Vec` to dodge the borrow checker is not.
- **Work in small steps.** Each step builds and passes the checks, so a failing check points
  at one change and the diff can be reviewed piece by piece.
- **Follow the project.** Before editing, read its agent and contributor docs (AGENTS.md,
  CLAUDE.md, CONTRIBUTING), the lint configuration and the CI workflow. Match the surrounding
  comment density and idiom. Where the project keeps docs in step with the code (a lifecycle
  table, a comment mapping rows to functions, a spec coverage table), update them in the
  same step.

## Size the work to the change

The safety net exists to catch behaviour changes that the existing tests would miss, so size
it to the change you plan:

- **Small.** One handler or a few helpers, no change to which fields hold state. Run the
  project's checks once before and once after, and skip everything marked *large* below. In
  the summary, map only the entity you touched.
- **Medium.** Several transitions or output helpers in one module. Run the checks before each
  step and at the end. Build a differential harness only if no existing test pins the exact
  outputs of the paths you change, and only over those paths. No fuzzing, no extra
  property-test cases, no benchmarks: the project's own checks at their normal settings are
  the right weight here.
- **Large.** Flags replaced by a phase enum, many writers of a state field merged into
  transitions, most handlers reshaped. Use the whole workflow.

Decide the size after the map (step 2). If the change grows partway through, move up a size
and say so in the summary.

## Workflow

### 1. Set up a safety net

Do this before the first edit, so that every later failure is yours and not pre-existing.

- **Note the base.** Run `git status` and note the base commit: every later comparison is
  against it. If files you plan to touch already have uncommitted changes, tell the user
  before you mix your edits into theirs. If you go ahead on top of them, use
  `git stash create` as the base: it records them as a commit without touching the tree.
- **Fix one check command.** Use the project's own if it has one (a CI workflow, a justfile,
  an xtask, the commands in its agent docs). Otherwise use the bundled gate:
  `<skill>/scripts/check.sh <repo> default all`. List the feature sets CI uses, e.g.
  `default all none tls`. The gate checks formatting without changing it, then runs clippy
  and the tests for each feature set, and exits non-zero if anything fails. Scope it to the
  package you change and the members that depend on it with
  `CHECK_PACKAGES="-p <crate> -p <dependent>"`, and run the whole workspace once at the end.
  If CI also runs something else (an MSRV check, extra lint flags), run that alongside.
- **If the baseline isn't green, don't fix it.** Record which checks fail and how, tell the
  user, and from then on expect the same failures and no new ones. Format only the files you
  edit. A failure that comes from the environment rather than the code (a global cargo
  config with nightly-only flags, a missing toolchain or tool) goes under Verification as
  "couldn't run", with the reason. If the repo has no CI, take the toolchain floor from
  `rust-version`, the edition and the language features in use, and say what you could and
  couldn't run.
- **Large changes: build a differential harness** when the existing tests don't pin the exact
  outputs of the paths you'll change. Pinning means trace or snapshot tests that assert the
  output sequence and the deadlines verbatim; assertions on the final state alone don't count.
  The harness runs the base and the working tree side by side on the same random calls and
  compares every output. `<skill>/scripts/difftest_scaffold.py` creates the crate pair and a
  template outside the repo. Filling in the template is the real work, so budget for it:
  read [references/differential.md](references/differential.md) first. Check that it catches
  one planted one-line mutant before you rely on it; one is enough.
- **Keep the harness cheaper than the refactor.** Drive the paths you restructure, not the
  whole crate. If covering a path would cost more than the change to it, report the gap
  under Verification instead and rely on that path's existing tests. Examples: a path behind
  TLS or encryption, nondeterminism you would have to normalize, a peer you would have to
  simulate.
- **Large changes only: run the slow checks once with more cases.** Run the property tests, sized
  to finish in a few minutes (ten times the default, or `PROPTEST_CASES=10000` when cases are
  cheap), and again at the end. Run a fuzz target only if it reaches code you'll change,
  time-boxed to 30–60 s. Run benchmarks only if a change will add work on a per-input path;
  restructuring control flow doesn't need them.
- **Fill coverage gaps that should outlive the change.** If a path you'll restructure has no
  coverage and you aren't building a harness, add tests that pin its current outputs first.
  If you are building one, it covers the gap for the refactor; add a test only for a
  behaviour it turns up that's worth keeping (a quirk you kept on purpose). Put new tests in a
  new file or module, as their own step, so the existing tests stay unchanged. The exception
  is the one `mod` line a single-crate test layout such as `tests/main.rs` needs.

### 2. Map the machine

Map the entities the request is about, and any entity a planned change would touch. In a
large crate where the request doesn't say which part matters, pick the entity the user named
and say what you left out. Write the map down before you change anything (a scratch file is
fine). It becomes the summary's state map, and often the module docs.

- **Entities.** For each entity in scope, list its fields and group them by the phase in
  which they mean something. Combinations of `bool`s and `Option`s that encode a phase
  between them are the main target.
- **Inputs.** Every `pub fn` that takes outside data or `now`, and what each can trigger.
- **Writers.** For each state field, every place that assigns it (search for `.field =`,
  `mem::replace`, `.take()`, `+= 1`). A field with many writers is a transition spread over
  the file.
- **Outputs.** Every push onto an output queue, and every deadline that `poll_timeout` reads.
- **Invariants.** What must always hold: an ID in exactly one map, a deadline set whenever
  something waits, a referenced connection that exists.
- **Quirks.** Behaviour that looks accidental: lenient parsing, odd precedence between two
  errors, a reply sent in answer to garbage, input still accepted after a deadline. You keep
  it (rule 1), but list it for the user.

Then write the map as a table: state, input, next state, outputs. Where you can't fill it in
from the code without tracing through several functions, the code isn't legible yet, and
that's where the work goes.

### 3. Choose the changes

[references/patterns.md](references/patterns.md) is the catalogue, with before/after examples
and the cases where each pattern doesn't pay off. Read its index, then the sections for
whatever your map turned up, including their "Not worth it" paragraphs. Read the whole file
for a large change. Rank candidate changes by how much each shortens the answer to one of the
four questions, against the size of the diff. The moves that usually pay off most:

- an enum whose variants carry each phase's data, in place of flags and options that encode
  the phase (pattern 1)
- one named function per transition, so each state field has few writers (pattern 2)
- handlers that match the input, decide, apply the transition and queue the outputs, along
  one consistent dispatch axis (pattern 3)
- one helper per kind of output, named after its intent (pattern 4)
- each deadline rule written once, with `poll_timeout` derived from state (pattern 5)
- the lifecycle written down where a reader lands, and invariants on the fields (pattern 9)

If the user named one function or one part, change only that and what it needs. A helper you
extract may be reused by its natural siblings, but don't rework code outside the request
just because the helper fits there too. List those improvements under Suggestions instead:
a reviewer who asked about one function shouldn't have to check a second one.

Leave out changes that only move code around, renames of local variables to suit a taste, and
anything that makes code longer without making a question easier to answer. When the user
asks for the move itself (splitting a long file into modules), see pattern 11. Code that
already reads well can stay as it is: say so in the summary rather than inventing work.

### 4. Apply in steps

Order the steps so that each is reviewable and none adds code that a later one deletes:

1. **Pure additions and extractions**: output helpers, named predicates, deadline helpers,
   feature-gated steps moved into helpers, wire encoding and parsing moved into functions
   (patterns 4, 5, 6, 10).
2. **The core change**: a phase enum, together with the transitions and handler shapes it
   forces (patterns 1–3, 7, 12). This often has to land as one step. If so, say why.
3. **Names** (pattern 8).
4. **Docs** (pattern 9).
5. **Reordering methods**, last and by itself, if at all (pattern 11).

Between edits, use a fast loop: clippy and the tests of the package you're changing, in the
default feature set, plus the harness if you built one. At the end of each step, run the
check command from step 1. Then make the step a commit if the user wants commits (they asked,
or the project's workflow expects them); otherwise leave the work uncommitted and list the
steps in the summary. Don't quiet a lint with scaffolding that the next step removes (a `cfg`
gate or an `#[allow]` added only to get one step green). Reorder the steps instead.

Drop a pattern at any spot where the borrow checker forces it into contortions, since
contorted code reads worse than what you started with. The usual signs:
- a method that takes a sibling field of `self` (an output queue such as
  `&mut VecDeque<Transmit>`) or its own map key as an argument, only to get past a borrow
- a `&self` method that takes a sub-struct only so it can read the config
- cloned keys or an extra lookup

The usual fixes:
- return the output and let the caller queue it
- put the helper on the entity and pass in the `Copy` config value it needs
- keep the code inline

### 5. Verify and summarize

Run the check command one last time, over the whole workspace, plus whatever else you ran at
the start: the slow checks and the harness.

Then check the public API, if the diff touches a `pub` item, a derive, a trait impl, a field
type (auto traits such as `Send` follow private fields) or a `cfg` on an item:
- Use `cargo semver-checks --baseline-rev <base>` once per feature set, with explicit flags:
  `--default-features`, `--all-features`, `--only-explicit-features` (none), and
  `--only-explicit-features --features x`.
- It catches only breaking changes, so also confirm that nothing new became public: use
  `cargo public-api diff` if installed, or read `git diff <base> | grep -E '^\+.*\bpub\b'`.
- If no tool is installed, ask before installing one, and otherwise report the API check as
  not run.
- If the diff touches only function bodies and private items, say that instead.

Then report in this shape:

```markdown
## State map
<the table from step 2, as the code reads now, compact>

## Changes
<one or two lines per step: what changed and where (file:line)>

## Left alone
<things you looked at and kept, and why; include names you kept when renaming their siblings>

## Suggestions
<improvements that need a public API or behaviour change, and the quirks from step 2 that
might be bugs, each with the test or harness case that pins it today>

## Verification
<the commands run and their results; the harness case count and the outcomes it reached or
missed; tests edited for private-item changes; anything that couldn't be run, and why>
```

Keep the prose to about 500 words, plus the table; for a small change, much less. The table
carries the detail, so the prose doesn't have to. Give one or two lines per change, and
leave out what the diff already shows, such as file-by-file narration and helper names you
introduced. Keep it factual. If a check failed or was skipped, say which one
and why. Don't vouch for code you can't see: if the user mentions drivers or downstream crates
outside the repo, say the public API is unchanged and how you checked, not that they need no
edits.
