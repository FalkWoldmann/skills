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
