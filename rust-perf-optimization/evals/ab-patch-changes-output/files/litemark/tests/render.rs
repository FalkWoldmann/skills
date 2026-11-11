use litemark::to_html;

#[test]
fn paragraphs() {
    assert_eq!(to_html("one\ntwo\n\nthree\n"), "<p>one\ntwo</p>\n<p>three</p>\n");
}

#[test]
fn emphasis_code_and_links() {
    assert_eq!(
        to_html("*a* `b` [c](http://e.com/?x=1&y=2)"),
        "<p><em>a</em> <code>b</code> <a href=\"http://e.com/?x=1&amp;y=2\">c</a></p>\n"
    );
}

#[test]
fn text_is_escaped() {
    assert_eq!(
        to_html("a & b < c > \"d\""),
        "<p>a &amp; b &lt; c &gt; &quot;d&quot;</p>\n"
    );
}

#[test]
fn code_is_escaped() {
    assert_eq!(to_html("`<b>&`"), "<p><code>&lt;b&gt;&amp;</code></p>\n");
}

#[test]
fn headings_get_unique_ids() {
    assert_eq!(
        to_html("# Hello, World\n\n# Hello world\n"),
        "<h1 id=\"hello-world\">Hello, World</h1>\n<h1 id=\"hello-world-1\">Hello world</h1>\n"
    );
}

#[test]
fn backslash_escapes() {
    assert_eq!(to_html("\\*not\\* \\[x] a\\b"), "<p>*not* [x] a\\b</p>\n");
}

#[test]
fn unclosed_constructs_are_text() {
    assert_eq!(to_html("2 * 3 [x] `y"), "<p>2 * 3 [x] `y</p>\n");
}

#[test]
fn crlf_line_endings() {
    assert_eq!(to_html("a\r\nb\r\n\r\nc\r\n"), "<p>a\nb</p>\n<p>c</p>\n");
}

#[test]
fn non_ascii_text() {
    assert_eq!(to_html("naïve *café* ☕"), "<p>naïve <em>café</em> ☕</p>\n");
}

#[test]
fn empty_input() {
    assert_eq!(to_html(""), "");
    assert_eq!(to_html("\n\n  \n"), "");
}
