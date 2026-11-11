# Checklist from The Rust Performance Book

A condensed, paraphrased checklist of [The Rust Performance Book](https://nnethercote.github.io/perf-book/)
by Nicholas Nethercote and others. The book is terse and links to real pull requests for most
items, so open the chapter when an item applies. It leans towards compiler-like workloads and
says so itself. Its compile-time chapter is left out here, because this skill is about runtime.

Use this list in step 5 to check that no cheap, well-known fix was overlooked, after the
profile has told you which area is hot. Every item is a candidate to measure, not a rule.

Contents: build configuration, lints, profilers, inlining, hashing, heap allocations, type
sizes, standard library types, iterators, bounds checks, I/O, logging and assertions, wrapper
types, machine code, parallelism, general tips.

## Build configuration

Cargo reads profile settings only from the workspace root, so these are the application's
choice. For a library, measure with the settings its benchmarks use and put anything else in
the report as a suggestion to users. Change one setting at a time and benchmark each.

| Setting | Effect | Cost |
|---|---|---|
| `codegen-units = 1` | may be faster and smaller | compile time |
| `lto = "thin"` or `lto = "fat"` | the book quotes 10 to 20% or more; fat is not always better than thin | compile time |
| `lto = "off"` | disables even the default thin-local LTO (`lto = false`) | slower code |
| `panic = "abort"` | smaller, slightly faster | no `catch_unwind` |
| `-C target-cpu=native` | lets the compiler use the build machine's instruction set | binary is not portable |
| an alternative allocator (`tikv-jemallocator`, `mimalloc`) | varies by program and platform | binary size, compile time |
| profile-guided optimisation with `cargo-pgo` | the book quotes 10% or more | set-up effort, not available through `cargo install` |

Check that `target-cpu=native` took effect by comparing `rustc --print cfg` with and without
it. `cargo-wizard` suggests a configuration. For size, the book lists `opt-level = "z"` or
`"s"` and `strip = "symbols"`, which makes profiling and backtraces harder.

## Lints

Run `cargo clippy` first: the book does not repeat what Clippy's perf group already reports,
and those fixes are usually simpler code as well. Two lints it names:

- `ptr_arg`: take `&[T]` instead of `&Vec<T>`, which also removes an indirection.
- `disallowed_types` in `clippy.toml`, to keep std types you replaced (`HashMap`, `Mutex`)
  from creeping back in.

## Profilers

The book's list, by what each answers:

- where time goes, sampling: `perf` (Linux; view with Hotspot or Firefox Profiler), `samply`
  (Mac, Linux, Windows), Instruments (macOS), VTune, AMD μProf, `flamegraph`.
- exact counts per function and line: Cachegrind and Callgrind.
- allocations, peak memory and hot `memcpy` calls: DHAT; `dhat-rs` works on all platforms with
  small code changes; heaptrack and bytehound on Linux.
- how often something happens: the `counts` tool on `eprintln!` output.
- what would pay off if it were faster: Coz, through `coz-rs`.

Use more than one. For readable profiles set `debug = "line-tables-only"` in the release
profile. std ships without debug info, so its frames stay coarse. If stacks are broken, build
with `-C force-frame-pointers=yes`; if names are mangled, try
`-C symbol-mangling-version=v0` or `rustfilt`.

## Inlining

- `#[inline]` suggests, `#[inline(always)]` and `#[inline(never)]` insist, none guarantee.
- Inlining is not transitive: to inline `g` through `f`, mark both.
- Good candidates are tiny functions and functions with one call site.
- A large function with one hot caller: make an `#[inline(always)]` version for the hot site
  and an `#[inline(never)]` wrapper for the others.
- The reverse works too: move rarely run code into a `#[cold]` function so the hot path
  compiles tighter.
- In Cachegrind output a function was inlined if its first and last lines carry no counts.
- Measure again afterwards. An attribute can make a neighbour stop being inlined, and the net
  effect can be zero or negative.

## Hashing

The default hasher resists collision attacks and is slow on short keys such as integers. If
hashing is hot and HashDoS is not a concern, try `rustc-hash` (`FxHashMap`, fastest, low
quality), `ahash` or `fnv`, and try more than one: in rustc, moving from fxhash to ahash was
1 to 4% slower, and back to the default 4 to 84% slower. For keys that are already random
integers, `nohash_hasher` skips hashing. Byte-wise hashing of padding-free types
(`#[derive(ByteHash)]` from `zerocopy` or `bytemuck`) is an advanced option whose effect
depends on hasher and layout.

## Heap allocations

An allocation costs about the same whether small or large. If `malloc` and `free` are hot,
lower the rate or change the allocator. In rustc, ten fewer allocations per million
instructions was worth about 1%.

- `Vec` grows 0, 4, 8, 16, ...: `Vec::with_capacity`, `reserve` or `reserve_exact` when the
  length is known. To learn typical lengths at a hot `push`, print them and post-process with
  `counts`.
- Many short vectors: `SmallVec<[T; N]>`. It reliably cuts allocations but is slightly slower
  per access and larger to move, so it is not a guaranteed win. `ArrayVec` when the maximum is
  known exactly.
- Strings: `String::with_capacity`; `smallstr` or `smartstring` for short ones. `format!`
  allocates, so use a literal where one works; `format_args!` or `lazy_format` can help.
- `a.clone_from(&b)` instead of `a = b.clone()` reuses `a`'s allocation.
- `Rc` and `Arc` clones do not allocate, but wrapping rarely shared values in them adds
  allocations.
- `to_owned`, `to_string` and `clone` on owning types allocate. Storing a borrow avoids it at
  the price of lifetimes; `Cow` covers data that is borrowed most of the time
  (`Cow::Borrowed`, `Cow::Owned`, `to_mut` for clone-on-write).
- Reuse collections: pass a `&mut Vec` in instead of returning a new one, or keep a working
  collection outside the loop and `clear` it.
- `BufRead::lines` allocates a `String` per line. Loop over `read_line` into one reused
  `String` when the body can work with a `&str`.
- Guard a hard-won reduction with an allocation-count test from `dhat-rs`.

## Type sizes

Shrinking a type that is instantiated often lowers memory traffic and cache pressure. Types
larger than 128 bytes are moved with `memcpy` calls, and DHAT's copy profiling finds the hot
ones.

- Measure with `size_of`, or the layout with `RUSTFLAGS=-Zprint-type-sizes cargo +nightly
  build --release` (the `top-type-sizes` crate condenses the output).
- The compiler already reorders fields, unless the type is `#[repr(C)]`.
- Box the fields of an enum's one oversized variant, best when that variant is rare.
- Store indices as `u32` or smaller and widen at use.
- `Vec::into_boxed_slice` gives a two-word `Box<[T]>`; `ThinVec` is one word and suits vectors
  that are often empty.
- Pin a size with a static assertion (for example `static_assertions::assert_eq_size!`),
  guarded by target architecture.

## Standard library types

- `vec![0; n]` for zero-filled vectors; it can use help from the OS.
- `Vec::swap_remove` is O(1) where `remove` is O(n), if order does not matter. `retain`
  removes many items in one pass.
- `ok_or`, `map_or`, `unwrap_or` and friends evaluate their argument eagerly. Use the closure
  forms when the fallback is expensive to build.
- `Rc::make_mut` and `Arc::make_mut` clone only when shared.
- `parking_lot` locks used to be reliably faster than std's. std has improved, so measure
  before switching.

## Iterators

- `collect` allocates. Skip it when the result is only iterated again, and prefer returning
  `impl Iterator` over a `Vec`.
- `extend` an existing collection instead of collecting and appending.
- Implement `size_hint` or `ExactSizeIterator::len` on your own iterators so `collect` and
  `extend` can reserve.
- `chain` can be slower than one iterator in hot code. `filter_map` can beat `filter` plus
  `map`.
- `chunks_exact` (with `remainder`) is faster than `chunks`, and likewise for the `r` and
  `_mut` variants.
- `iter().copied()` for small element types can produce better code. Check the machine code.

## Bounds checks

They matter less often than expected. Safe ways to remove them in a hot loop: iterate instead
of indexing, take a slice of the `Vec` before the loop and index that, or assert the index
range up front. `get_unchecked` is the unsafe last resort.

## I/O

- `println!` locks stdout on every call: take `stdout().lock()` once for many writes.
- Files and sockets are unbuffered: wrap them in `BufReader` or `BufWriter` for many small
  operations, and `flush` a writer explicitly, because errors during drop are swallowed.
- Reading into a `String` validates UTF-8. When bytes are enough, use `BufRead::read_until`,
  or the `bstr` and `linereader` crates.

## Logging and assertions

Make sure no work that feeds logging or debugging runs when it is switched off. `assert!` runs
in release builds; `debug_assert!` does not, and is the choice for hot checks that safety does
not depend on.

## Wrapper types

Going through `RefCell` or `Mutex` has a cost per access. Values that are usually accessed
together can share one wrapper (`Arc<Mutex<(A, B)>>` instead of two), depending on the access
pattern.

## Machine code

For a small, very hot piece, read the assembly: Compiler Explorer for snippets,
`cargo-show-asm` inside a project. `core::arch` has the architecture intrinsics.

## Parallelism

Out of the book's depth, and often out of scope for a library: `rayon` and `crossbeam` for
threads, and a linked overview of SIMD in Rust for data parallelism. Whether a library may
spawn threads is a design question for its maintainer.

## General tips

- The largest wins come from algorithms and data structures, before low-level tweaks.
- Optimise only hot code, because optimised code is harder to read.
- For a hot function there are two options: make it faster, or call it less.
- Removing a silly slowdown is easier than inventing a clever speed-up.
- Compute lazily. Check the cheap common case first, and special-case collections of zero, one
  or two elements when small sizes dominate.
- Measure how often each case occurs and handle the frequent ones first.
- A small cache in front of a lookup with high locality can win.
- For repetitive data, store common values compactly and the rare ones in a side table.
- Many small gains add up.
- Leave a comment on non-obvious optimised code, with the measurement that justified it.
