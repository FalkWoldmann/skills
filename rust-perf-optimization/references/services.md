# Clients, servers and runtimes

For code whose speed shows up as throughput or latency against another process: a Kafka or
database client, an HTTP server, an async runtime, anything on a socket. Instruction counts of
one deterministic run do not capture batching, wake-ups, syscalls or waiting, so this kind of
work needs two harnesses, and the steps of the skill map onto them like this.

Contents: two harnesses, the load harness, what to record, profiling under load, the
correctness check, what changes in each step, pitfalls.

## Two harnesses

| | Isolated driver | Load harness |
|---|---|---|
| What it runs | one CPU-bound path with no peer: encode a batch, decode a fetch response, parse a frame, poll a ready task | the real client or server against a real peer |
| Metric | instructions and allocations (callgrind, DHAT) | throughput, CPU time per unit of work, latency percentiles, peak memory |
| Good for | finding and ranking changes in encoding, decoding, checksums, compression, buffer handling | proving that a change matters end to end, and finding costs in I/O, batching and scheduling |
| Noise | none | real, needs alternation and a quiet machine |

Use the isolated driver for steps 3 to 7 wherever the profile says the cost is CPU work in the
crate. Many crates already have one: benches with names like `protocol`, `send_path` or
`encode` that need no broker. Use the load harness to find out where the time goes in the
first place and for step 8.

A change that only shows up in the load harness (a different flush policy, fewer wake-ups,
bigger reads, pipelining) cannot be ranked by instruction counts. Measure it with the load
harness alone and treat the result with more suspicion, because that harness is noisy.

## The load harness

If the project or the user already has one, use it and read its rules before touching it. A
good one has these properties, and they are the checklist for building one:

- The peer is real and pinned down: broker or server version, its configuration, topic or
  schema layout, and whether it shares the machine with the client.
- Client and peer run on separate cores (`taskset`, or the harness's own setting), so the
  client's CPU time is its own.
- Every variant gets the same settings, written down in one file. A setting that exists only
  in one client is set on purpose and the reason is recorded.
- Each variant is its own process, so its threads, CPU time and peak memory are not mixed with
  another's.
- There is a warm-up round that is not counted, several measured rounds, and the order of
  variants rotates between rounds.
- The clock covers a defined span (first record to last acknowledgement), and connecting is
  outside it.
- The raw results and the state of the machine (CPU, kernel, toolchain, crate versions) are
  stored with the run.

To compare two versions of the same crate, build the harness's client binary once per version
(a `[patch]` section or a path dependency pointing at each checkout) and add both as variants.
Then the harness alternates them like any two clients.

Several variants of one crate in one workspace need different version numbers, because a
lockfile cannot hold two path packages with the same name and version. Bump the patch version
in each copy (`0.30.1001`, `0.30.1002`) and build once without `--locked`.

A fake or in-process peer reproduces the client's CPU cost per record, which makes it a good
isolated driver. It does not reproduce what a real peer limits: fetch sizes, round trips,
back-pressure. A setting that throttles the client against a real broker can be invisible
against the fake one.

## What to record

- Throughput in units of work per second, as the median over rounds, with the range.
- CPU seconds for the fixed amount of work, user plus system. A change often leaves throughput
  alone, because the peer or the network is the limit, and shows up only here.
- Peak memory.
- Latency percentiles (p50, p99, p99.9) when the workload has a request and a response. Drive
  it at a fixed offered rate below saturation and measure from the time a request was due, not
  from the time it was sent, or a stalled client hides its own delays (coordinated omission).
- Syscall counts per unit of work (`strace -c -f`, or `perf stat -e 'syscalls:*'`) when the
  change is about I/O.

Say which limit a scenario is hitting. If the peer is at 100% of its cores, a faster client
cannot raise the rate, and CPU seconds is the number to watch.

## Profiling under load

Sample the client while the load harness runs: `perf record -g -p <pid>` on Linux, or
`samply record`. Build with line tables (`debug = "line-tables-only"` or `debug = 1` in the
release profile) and, if stacks are cut short, with `-C force-frame-pointers=yes`. Read the
profile for three things:

- CPU in the crate's own code: candidates for the isolated driver.
- CPU in the kernel under `send`, `recv`, `epoll_wait`, `io_uring_enter`, `futex`: too many
  small writes, too many wake-ups, or lock contention. The fix is structural (batch, coalesce,
  reuse), and its proof is the load harness.
- CPU in the allocator and in `memcpy`: buffers that are created per message or copied between
  layers.

For async code also look at how often tasks are woken per unit of work. A runtime's metrics or
a counter around the poll function shows it; ten polls per message means the work is cut too
fine.

Valgrind tools serialise threads and slow the process 20 to 50 times, which changes timing
behaviour (batches fill differently, timeouts fire). Use them on the isolated driver, not on
the client under load.

## The correctness check

Output hashes become delivery checks: every record sent was acknowledged, every record
consumed was the one produced, in order per partition, with no duplicates and none missing.
Compare counts and a checksum over payloads at least; for a protocol codec, round-trip random
messages through old and new and compare bytes. Run the crate's integration tests against the
real peer as CI does, because a client can be fast by skipping work: not waiting for an
acknowledgement, dropping a flush, ignoring an error path.

Keep the delivery guarantees fixed across variants (`acks`, idempotence, fsync settings). A
gain that comes from weakening one is a different product.

## What changes in each step

1. Orient: also read how the project or the benchmark repository wants clients configured, and
   which scenarios it reports.
2. Workload: the scenarios of the load harness are the main workload. Guards are the scenarios
   a change could hurt: tiny records, huge records, one partition, many partitions, a slow
   peer, compression on.
3. Baseline: one run of the load harness for the unchanged crate, plus instruction counts of
   the isolated drivers.
4. Profile: sampling under load first, then line-level profiles of the isolated drivers for
   the hot CPU paths.
5. Candidates: sort them into "CPU path" and "I/O or scheduling", because they are measured
   differently.
6. Prototype: CPU-path changes against the isolated driver; the others against the load
   harness with at least five alternating rounds.
7. Refute: guards from step 2, the delivery check, the integration tests, and a look at
   whether the gain survives when the peer is the bottleneck.
8. Confirm: every survivor, including the CPU-path ones, in the load harness. Report rate and
   CPU seconds.

## Pitfalls

- Client and peer on the same cores: the faster client starves the broker and looks slower.
- A default that throttles one variant (a queue back-off, a poll limit) decides the result
  instead of the code. Find these before comparing, and record what was set.
- Comparing rates when the peer is saturated.
- Loopback hides network cost and makes syscall overhead look larger than in production. Say
  that results are from one machine.
- A short run measures connection set-up and the first batch. Run long enough that the rate
  is flat, tens of seconds or millions of records.
- Garbage collection or compaction in the peer (a JVM broker) lands in some rounds. Use the
  median and look at the range.
