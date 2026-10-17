//! Differential harness: drive the original crate (`orig`) and the working
//! tree (`new`) through the same random sequence of public calls and compare
//! everything they hand back. See the skill's references/differential.md.
//!
//! cargo run --release -- <cases> [seed]          (add --features ... as needed)

// Remove once the TODOs are filled in.
#![allow(unused)]

use std::time::{Duration, Instant};

/// xorshift64*: small, deterministic, good enough to pick operations.
struct Rng(u64);

impl Rng {
    fn new(seed: u64) -> Self {
        Rng(seed.wrapping_mul(0x9e37_79b9_7f4a_7c15) | 1)
    }
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_f491_4f6c_dd1d)
    }
    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
    fn chance(&mut self, percent: u64) -> bool {
        self.below(100) < percent
    }
    fn pick<'a, T>(&mut self, items: &'a [T]) -> &'a T {
        &items[self.below(items.len() as u64) as usize]
    }
}

/// One generated operation, independent of either crate's types, so both
/// sides receive exactly the same input.
#[derive(Debug, Clone)]
enum Op {
    // TODO: one variant per public input, with plain data only. For example:
    // Datagram { from: u8, bytes: Vec<u8> },
    // Read(Vec<u8>),            // a chunk of a stream; split whole messages at random
    // Timeout,                  // call handle_timeout at the current time
    Advance(Duration), // move `now` (also try zero, exactly to the deadline, and backwards if the API allows it)
}

/// A whole case: the configuration plus the operations, so a failure can be
/// printed and replayed.
#[derive(Debug, Clone)]
struct Case {
    // TODO: config knobs as plain data, including degenerate values
    // (zero durations, zero retries, out-of-range sizes).
    ops: Vec<Op>,
}

/// Length of the occasional very long case; lower it if one case is expensive
/// (a handshake per case, large buffers).
const LONG_CASE_OPS: usize = 20_000;

fn generate(rng: &mut Rng) -> Case {
    // TODO: mostly well-formed protocol traffic (valid replies, the expected
    // sequence numbers, the right peer), mutated at random: wrong source, stale
    // or duplicated messages, truncation, random bytes, boundary lengths
    // (0, 1, max, max + 1). Now and then a very long case, so counters and
    // sequence numbers wrap.
    let len = if rng.chance(1) { LONG_CASE_OPS } else { 1 + rng.below(40) as usize };
    let ops = (0..len)
        .map(|_| Op::Advance(Duration::from_millis(*rng.pick(&[0, 1, 10, 1000]))))
        .collect();
    Case { ops }
}

/// Instantiates the same driver over both crates. `$krate` is `orig` or `new`.
/// Every output is rendered as a string, so the two crates' distinct types
/// compare directly.
macro_rules! driver {
    ($name:ident, $krate:ident) => {
        fn $name(case: &Case, start: Instant, log: &mut Vec<String>) {
            let mut now = start;
            // TODO: build the machine from `case`'s config, e.g.
            // let mut m = $krate::Resolver::new(config_from(case));
            // Seed every RNG inside the machine identically on both sides, or
            // normalize what it feeds into outputs (see differential.md).
            for (i, op) in case.ops.iter().enumerate() {
                match op {
                    Op::Advance(d) => now += *d,
                }
                // TODO: after every call, drain every output and record it:
                // while let Some(t) = m.poll_transmit() { log.push(format!("{i} transmit {t:?}")); }
                // while let Some(e) = m.poll_event() { log.push(format!("{i} event {e:?}")); }
                // log.push(format!("{i} timeout {:?}", m.poll_timeout().map(|t| t - start)));
                let _ = (i, now);
            }
        }
    };
}

driver!(run_orig, orig);
driver!(run_new, new);

fn main() {
    let mut args = std::env::args().skip(1);
    let cases: u64 = args.next().and_then(|s| s.parse().ok()).unwrap_or(10_000);
    let seed: u64 = args.next().and_then(|s| s.parse().ok()).unwrap_or(1);
    let start = Instant::now();
    // A panic is an output too: record it instead of dying without the case.
    std::panic::set_hook(Box::new(|_| {}));
    let run = |f: fn(&Case, Instant, &mut Vec<String>), case: &Case| {
        let mut log = Vec::new();
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| f(case, start, &mut log)));
        if let Err(e) = result {
            let msg = e
                .downcast_ref::<String>()
                .cloned()
                .or_else(|| e.downcast_ref::<&str>().map(|s| s.to_string()));
            log.push(format!("panic {msg:?}"));
        }
        log
    };
    let mut outcomes = std::collections::BTreeMap::<String, u64>::new();
    for n in 0..cases {
        let mut rng = Rng::new(seed ^ n);
        let case = generate(&mut rng);
        let (a, b) = (run(run_orig, &case), run(run_new, &case));
        if a != b {
            let at = a.iter().zip(&b).position(|(x, y)| x != y).unwrap_or(a.len().min(b.len()));
            eprintln!("MISMATCH in case {n} (seed {seed}) at output {at}");
            eprintln!("case: {case:#?}");
            eprintln!("orig: {:#?}", &a[at.saturating_sub(3)..a.len().min(at + 3)]);
            eprintln!("new:  {:#?}", &b[at.saturating_sub(3)..b.len().min(at + 3)]);
            std::process::exit(1);
        }
        // Coverage: count each kind of output (the text before the first `(`
        // or `{` after the step number), so the report can say what was reached.
        for line in &a {
            let kind: String = line
                .split_once(' ')
                .map_or(line.as_str(), |(_, rest)| rest)
                .chars()
                .take_while(|c| *c != '(' && *c != '{' && *c != ',')
                .collect();
            *outcomes.entry(kind.trim().to_string()).or_default() += 1;
        }
    }
    println!("{cases} cases identical (seed {seed})");
    for (kind, count) in outcomes {
        println!("{count:>12}  {kind}");
    }
}
