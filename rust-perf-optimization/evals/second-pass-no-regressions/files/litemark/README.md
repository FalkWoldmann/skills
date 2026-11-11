# litemark

A small inline markup to HTML converter. It understands paragraphs separated by blank lines,
`# ` headings with generated ids, `*emphasis*`, `` `code` ``, `[links](url)` and backslash
escapes. Everything else is text and gets HTML-escaped.

```rust
assert_eq!(litemark::to_html("hello *world*"), "<p>hello <em>world</em></p>\n");
```

There is a command line tool as well: `litemark FILE` writes the HTML to standard output.

## Benchmark

The benchmark renders a generated corpus of about 3 MB:

```sh
python3 scripts/gen-corpus.py > bench/corpus.txt
cargo bench
```

It prints the median time of 15 runs.

## Changes

0.4.0 removed most allocations from rendering: tokens borrow from the input, blocks are
slices of it, and escaping writes straight into the output. The benchmark went from about
32 ms to about 3 ms. Output is identical to 0.3.
