# Patterns for readable sans-IO state machines

Each pattern says what to look for, what to change, and when not to bother. The examples are
generic; fit them to the crate's names and conventions.

1. Phase enum with per-phase data
2. One function per transition
3. Decide, then act
4. Output helpers named by intent
5. Deadlines with a name
6. Lookups by ID: stale input or broken invariant
7. Exhaustive matches over your own enums
8. One word per concept
9. Docs where the reader lands
10. Feature-gated code out of the main flow
11. Method order and module layout
12. One place for completion
13. Typestate: usually not here

## 1. Phase enum with per-phase data

**Look for** fields that only mean something in some phases, and flags whose combinations
encode the phase:

```rust
struct Conn {
    connecting: bool,
    handshake_done: bool,
    session: Option<Session>,     // Some once the handshake starts
    close_reason: Option<Error>,  // Some once closing
    retries: u32,                 // only used while connecting
}
```

A reader has to work out which of the 2 × 2 × 2 × 2 combinations can happen, and every
handler has to check them again.

**Change** to an enum whose variants hold exactly the data that exists in each phase, and
keep the fields shared by every phase outside it:

```rust
struct Conn {
    server: SocketAddr,
    phase: Phase,
}

enum Phase {
    Connecting { retries: u32 },
    Handshaking(Session),
    Open(Session),
    Closing(Error),
}
```

Move between phases with `mem::replace` or by matching on `&mut self.phase`, without
cloning:

```rust
let Phase::Handshaking(session) = mem::replace(&mut self.phase, Phase::Closing(Error::Reset))
else { return };
self.phase = Phase::Open(session);
```

**Not worth it** when nearly every field is shared and only one flag differs (a `bool` named
for its meaning is fine), or when the variants would force a `mem::replace` dance into every
handler. A "phase" enum next to shared fields is often the middle ground. Also skip it if the
type is `pub` with public fields: that's an API change, so suggest it instead.

## 2. One function per transition

**Look for** a state field assigned in many places (`p.route = ...` in four functions,
`self.state = State::Closed` spread through the handlers), or the same three lines (set the
state, reset the deadline, queue a send) repeated with small differences.

**Change** so that each transition is one named function that does all of it: checks it's
allowed, updates the state, resets what the new state needs, queues the outputs. Name it
after the transition in the protocol's terms (`switch_to_tcp`, `start_handshake`,
`begin_close`), not after the mechanics (`set_route`, `update`). Then the list of transitions
is the list of those functions, and a reader can check each against the spec on its own.

When transitions differ in their accounting (one uses up a retry budget, another is free, a
third is free once), say so in each function's doc, and where the rules matter, in one comment or
table that lists every transition and its rule.

**Not worth it** for a field that really is plain data (a byte counter, a last-activity
timestamp) and isn't part of the phase.

## 3. Decide, then act

**Look for** `handle_*` functions that interleave validation, lookups, decisions and side
effects over fifty lines, so the input's effect on the state is hard to see.

**Change** each handler into the same shape: find the entity and ignore stale input, decide
what happened (often a `match` on the input or the current phase), then call the transition
from pattern 2. The handler then reads like a row of the state table.

```rust
pub fn handle_datagram(&mut self, query: QueryId, from: SocketAddr, data: &[u8], now: Instant) {
    let Some(pending) = self.pending.get(&query) else { return }; // stale: already done
    if !pending.expects_datagram_from(from) { return }
    let Ok(response) = Message::from_vec(data) else { return };
    if pending.is_answered_by(&response) {
        self.handle_response(query, response, now);
    }
}
```

When the borrow checker won't let a decision on `&mut entity` call a method on `&mut self`,
one way through is to return a small `enum Action` from the decision and apply it after the
borrow ends. Use it only when it makes the handler clearer. For two branches, an early return
is plainer.

**Pick one dispatch axis.** A machine has two axes, state × input. Choose one outer match
and keep it throughout. State-first (`match self.state { S => match input { .. } }`) keeps
each row of the state table in one place, and it's the better default when a reader asks
"what does this state do". Input-first handlers (`handle_data`, `handle_error`, each matching
every state) suit machines where most inputs mean the same thing in every state. They spread
one state over several functions, so they need the module's state table to compensate.

**Name decision results.** A helper that reports more than success or failure should return
`Option<T>` or a small enum (`Step::NeedMore`, `Step::Advanced(next)`), not a `bool` or a
`Result<bool, _>` whose meaning lives only in the doc comment. `if check_tid(from)` makes
the reader look up whether `true` means keep or drop; `if !self.is_from_peer(from)` doesn't.

**Split independent sweeps.** A handler that does two unrelated passes (expire the queries
that are due, then close the idle connections) reads better as two named steps called in the
same order: `self.expire_queries(now); self.close_idle_connections(now);`.

## 4. Output helpers named by intent

**Look for** `self.transmits.push_back(Transmit { ... })` or event construction spelled out
at many call sites, especially when they differ only in one field.

**Change** to one private helper per kind of output: `queue_close(connection)`,
`queue_datagram(query, server)`, `complete(query, outcome)`. All the outputs a transition can
produce then show up at a glance, and the struct literal lives in one place.

**Careful** with the order: a helper must push onto the queues in the same order as the code
it replaces. Queue order is behaviour (the driver carries out transmits in that order, and
tests pin it).

## 5. Deadlines with a name

**Look for** the same deadline arithmetic in many places (`now.checked_add(self.config.timeout)`
six times), deadline fields whose `None` means different things in different places, and
timer bookkeeping kept apart from the state it belongs to (a separate `next_timeout` field
that has to be kept in sync by hand).

**Change** the formula into a named helper (`fresh_deadline(now)`, `idle_deadline(conn)`),
document what `None` means on the field itself ("`None` if `now + timeout` overflows: waits
forever"), and derive `poll_timeout` from the state (the minimum over the deadlines that
exist) rather than from a cached value. In each transition's doc, say whether it starts the
deadline over or keeps it, since that is where subtle bugs hide.

A borrow conflict is not a reason to leave the formula copied: if a `&self` helper clashes
with a `&mut` borrow of the entity, put the helper on the entity and pass in the config value
it needs, which is usually `Copy`:

```rust
impl Pending {
    /// Starts this attempt's deadline over; `None` if it would overflow.
    fn restart_deadline(&mut self, now: Instant, timeout: Duration) {
        self.deadline = now.checked_add(timeout);
    }
}
// at the call site, with `pending` borrowed mutably out of `self.pending`:
pending.restart_deadline(now, self.config.timeout);
```

When you're done, search for the formula (`checked_add(`, `+ self.config.timeout`). It
should appear once per rule, with every path that restarts that deadline going through the
helper.

**Not worth it**: wrapping `Instant` in a newtype for its own sake.

## 6. Lookups by ID: stale input or broken invariant

**Look for** `let Some(x) = self.map.get_mut(&id) else { return };` all over the internal
functions. Some of these protect against stale input from the driver (a datagram for a query
that already finished, which is normal), and others against something that cannot happen (an
internal function called with an ID its caller just looked up). The two look identical, so a
reader can't tell which absences are expected.

**Change**: at driver-facing entry points, keep the silent return and document it on the
`pub fn` ("ignored if the query is no longer pending"). For internal calls, make the
impossible case visibly impossible, in whatever way the crate's lints allow: a
`debug_assert!`, a comment stating the invariant, or a signature that takes the entity
(`&mut Pending`) or its data instead of an ID to look up again. Don't add `unwrap`, `expect`
or `panic!` where the lints deny them.

## 7. Exhaustive matches over your own enums

**Look for** `_ =>` arms or `matches!(..)` checks on the crate's own state enums, where a new
variant would quietly take the default branch.

**Change** to listing the variants, so that adding a state makes the compiler point at every
decision that needs revisiting. Wildcards over foreign enums (response codes, error kinds)
are fine; often they're unavoidable.

## 8. One word per concept

**Look for** synonyms for one thing (`retry`, `resend`, `reissue`, `emit` and `send` all
meaning "put a message on the wire") and one word for two things (`attempt` as both a counter
and a message).

**Change** private names so that each concept has one word, and verbs follow the role:
`handle_*` for inputs from the driver, `poll_*` for outputs, protocol verbs for transitions,
plain nouns for queries without side effects. Where several similar words have to stay
because they mean different things (`retry` uses up an attempt, `resend` doesn't), define them
in one place, in the module docs or the comment over the transitions.

Names come in families: the receive buffer, the write queue, the event queue; or the
counters and deadlines of one entity. When you rename one member, check the others, so you
don't end up with `received`, `out` and `events` side by side. List any you keep under "Left
alone".

Rename only where the current name misleads or conflicts. A rename that merely suits your
taste costs review time and buys nothing.

## 9. Docs where the reader lands

**Look for** lifecycle knowledge that exists only implicitly in the code, or only in a design
doc or a PR description.

**Change**: put the lifecycle in the doc comment of the type that holds the state, or in the
module docs, whichever a reader opens first.

**Table or diagram.** Prefer a `State | Input | Next state | Outputs` table. It's right the
first time, shows guards and accounting in a column, and stays readable at twenty rows.
Write the labels Mealy-style: the input is a `handle_*` call or a deadline passing, the
guard is in brackets (`[attempts left]`, `[not yet resent]`), and the outputs are the
transmits and events queued. Add a diagram only for shape a table hides, such as the main
path through the states. Keep it to a simple chain or a handful of boxes, and draw it after
the code has settled, because a box diagram drawn early is usually wrong. When transitions
carry accounting rules (free once, uses an attempt, deadline kept or restarted), the table
is the place for them; a diagram can't show them legibly.

**One diagram or table per entity** (query, connection, stream), not their product, which
explodes in size.

**Tools.** ASCII in the rustdoc comment renders everywhere (docs.rs, IDE hovers, diffs)
without dependencies, so make it the default. Mermaid `stateDiagram-v2` renders on GitHub,
and in rustdoc through a doc-time crate such as `aquamarine`. Suggest it if the project
already uses it, or if the README wants a picture, but don't add the dependency yourself.
D2, PlantUML and committed SVGs need a build step and drift from the code, so leave them for
design docs.

Document invariants on the fields they constrain ("every `QueryId` in flight is
in exactly one place"). Comments in function bodies should say why ("one message at a time:
acting on an answer may close this connection"), never narrate what the next line does. Cite
the RFC section where a rule comes from a spec. Write the comments in the crate's own voice
and density: three good comments beat thirty.

## 10. Feature-gated code out of the main flow

**Look for** `#[cfg(feature = "...")]` blocks in the middle of a handler, so a reader has to
mentally compile both versions to follow the logic.

**Change**: move the feature-specific step into a helper, so the handler reads the same in
every build.
- **When the build without the feature would be a pass-through**, give the helper one body
  with the `cfg` inside it.
- **When the two builds really differ**, use one `cfg`-gated body per feature set. Twin
  functions that need `#[expect(clippy::unnecessary_wraps)]` or `_`-prefixed parameters in
  one build are a sign the split went too far.
- **Keep gates on whole items that only the feature uses** (a variant, an encoder, a
  parser), and remove only the statement-level `cfg`s inside handlers. If un-gating
  something makes feature code compile into builds where it can never run, say so in the
  summary.

Check that every feature combination still compiles and passes, and that lint expectations
still hold in each one.

## 11. Method order and module layout

**Look for** public inputs, public outputs and internal transitions mixed together in one
`impl` block.

**Change** the order to: constructor; inputs (`query`, `handle_*`, `cancel`); outputs
(`poll_*`); then the private transitions grouped by the entity they act on; then small
helpers. Add section comments (`// Inputs`, `// Outputs`, `// Transitions`) only if the project
already uses them or the `impl` block runs to several hundred lines; otherwise the order
alone is the signpost. Don't add a table of contents of the file to the module docs, because
it goes stale with the next added function.

This is the cheapest change with the noisiest diff, so do it last, by itself, and only if
the file is long enough for it to matter. Move whole methods, with their doc comments and
attributes attached. Then prove the step only moves code. Before you start, save the file
(`cp src/x.rs <scratch>/x.before.rs`), and afterwards run
`diff <(sort <scratch>/x.before.rs) <(sort src/x.rs)`. The sorted lines must match, apart
from any section comments you added.

**Splitting a long file into modules.** Do this when it is asked for, or when one file holds
several entities that a reader looks at separately. Split along the same lines: one module
per entity or per role (the inputs and outputs in `mod.rs`, stream connections in
`stream.rs`, wire encoding in `wire.rs`). Don't split one transition across files.
- **Keep the public API's paths.** Re-export from the old module path, so `crate::resolver::X`
  and every rustdoc link keep working. Make moved private items no more visible than they
  need to be (`pub(super)` before `pub(crate)`).
- **Keep it a pure move.** `impl Resolver` blocks can live in several files, so methods can
  move without changing. Prove it with the same sorted-lines diff over the concatenation of
  the new files, allowing only `mod`/`use` lines and visibility changes. Move first, in its
  own step, and make no other edits in that step.
- **Update every reference to file paths:** module docs, AGENTS.md, and comments that say
  "in resolver.rs".

## 12. One place for completion

**Look for** two or more places that finish an entity and build its outcome events: the
success path and the failure path each removing the entry and copying the outcome to
everyone waiting on it (joined requests, stream readers, subscribers), each in a slightly
different order.

**Change** to one function that removes the entity and queues its outcome
(`finish(id, Outcome)`), with success and failure as an argument. The rule for who gets
notified, and in what order, then lives in one place. Keep the order of the events exactly as
it was.

## 13. Typestate: usually not here

Typestate (`Conn<Handshaking>` becoming `Conn<Open>`) encodes phases in types and works well
for builders and one-shot handshakes the caller drives step by step. A sans-IO machine is
different: the driver holds one value for its whole life and feeds it inputs in any order,
so the phase is runtime data. Moving it into types would push the `match` onto the driver and
change the public API. Prefer pattern 1. Suggest typestate only for a sub-part the caller
really does drive linearly, and only as a suggestion.
