//! litemark: a small inline markup to HTML converter.
//!
//! Blocks are separated by blank lines. A block that starts with `# ` is a heading and gets
//! an id made from its text; every other block is a paragraph. Inside a block, `*text*` is
//! emphasis, `` `text` `` is code and `[text](url)` is a link. A backslash before one of the
//! special characters makes it literal.

use std::collections::HashMap;

use memchr::{memchr, memrchr};

/// Bytes that can start an inline construct.
const SPECIALS: &[u8] = b"*`[\\";

#[derive(Debug, PartialEq)]
pub(crate) enum Token<'a> {
    Text(&'a str),
    Emph(&'a str),
    Code(&'a str),
    Link { text: &'a str, url: &'a str },
}

/// Converts `input` to HTML.
pub fn to_html(input: &str) -> String {
    let mut out = String::new();
    let mut ids: HashMap<String, usize> = HashMap::new();
    each_block(input, |block| match block.strip_prefix("# ") {
        Some(title) => {
            out.push_str("<h1 id=\"");
            out.push_str(&unique_id(&mut ids, title));
            out.push_str("\">");
            render_inline(title, &mut out);
            out.push_str("</h1>\n");
        }
        None => {
            out.push_str("<p>");
            render_inline(block, &mut out);
            out.push_str("</p>\n");
        }
    });
    out
}

/// The block that the lines read so far belong to.
enum Block {
    /// The last line was blank, or there was none yet.
    None,
    /// `input[start..end]` is the block as it is: its lines are separated by a lone `\n`.
    Borrowed { start: usize, end: usize },
    /// A `\r` was dropped between two lines of the block, so it is built up in a buffer.
    Joined,
}

/// Splits the input into blocks at blank lines and calls `emit` with each one. Lines inside a
/// block are joined with `\n`, and a `\r` before the line end is dropped.
fn each_block(input: &str, mut emit: impl FnMut(&str)) {
    let mut joined = String::new();
    let mut block = Block::None;
    let mut pos = 0;
    while pos < input.len() {
        let line_start = pos;
        let line = match memchr(b'\n', &input.as_bytes()[pos..]) {
            Some(i) => {
                pos += i + 1;
                &input[line_start..pos - 1]
            }
            None => {
                pos = input.len();
                &input[line_start..]
            }
        };
        let line = line.strip_suffix('\r').unwrap_or(line);
        if line.trim().is_empty() {
            match std::mem::replace(&mut block, Block::None) {
                Block::None => {}
                Block::Borrowed { start, end } => emit(&input[start..end]),
                Block::Joined => emit(&joined),
            }
        } else {
            let line_end = line_start + line.len();
            block = match block {
                Block::None => Block::Borrowed { start: line_start, end: line_end },
                // Only a `\n` lies between the last line and this one.
                Block::Borrowed { start, end } if end + 1 == line_start => {
                    Block::Borrowed { start, end: line_end }
                }
                Block::Borrowed { start, end } => {
                    joined.clear();
                    joined.push_str(&input[start..end]);
                    joined.push('\n');
                    joined.push_str(line);
                    Block::Joined
                }
                Block::Joined => {
                    joined.push('\n');
                    joined.push_str(line);
                    Block::Joined
                }
            };
        }
    }
    match block {
        Block::None => {}
        Block::Borrowed { start, end } => emit(&input[start..end]),
        Block::Joined => emit(&joined),
    }
}

#[cfg(test)]
fn split_blocks(input: &str) -> Vec<String> {
    let mut blocks = Vec::new();
    each_block(input, |block| blocks.push(block.to_string()));
    blocks
}

fn unique_id(ids: &mut HashMap<String, usize>, title: &str) -> String {
    let mut slug = String::new();
    for ch in title.chars() {
        if ch.is_alphanumeric() {
            slug.extend(ch.to_lowercase());
        } else if !slug.ends_with('-') {
            slug.push('-');
        }
    }
    let slug = slug.trim_matches('-');
    match ids.get_mut(slug) {
        Some(seen) => {
            *seen += 1;
            format!("{}-{}", slug, *seen - 1)
        }
        None => {
            ids.insert(slug.to_string(), 1);
            slug.to_string()
        }
    }
}

fn is_special(b: u8) -> bool {
    SPECIALS.contains(&b)
}

#[cfg(test)]
pub(crate) fn lex(s: &str) -> Vec<Token<'_>> {
    let mut tokens = Vec::new();
    lex_each(s, |token| tokens.push(token));
    tokens
}

/// Calls `emit` with each token of `s` in order.
fn lex_each<'a>(s: &'a str, mut emit: impl FnMut(Token<'a>)) {
    let bytes = s.as_bytes();
    let mut i = 0;
    let mut link_tail = LinkTail::Unknown;
    while i < bytes.len() {
        match bytes[i] {
            b'\\' if i + 1 < bytes.len() && is_special(bytes[i + 1]) => {
                emit(Token::Text(&s[i + 1..i + 2]));
                i += 2;
            }
            b'*' => match memchr(b'*', &bytes[i + 1..]) {
                Some(len) if len > 0 => {
                    emit(Token::Emph(&s[i + 1..i + 1 + len]));
                    i += len + 2;
                }
                _ => {
                    emit(Token::Text("*"));
                    i += 1;
                }
            },
            b'`' => match memchr(b'`', &bytes[i + 1..]) {
                Some(len) if len > 0 => {
                    emit(Token::Code(&s[i + 1..i + 1 + len]));
                    i += len + 2;
                }
                _ => {
                    emit(Token::Text("`"));
                    i += 1;
                }
            },
            b'[' => match link_tail.link_at(s, i) {
                Some((token, end)) => {
                    emit(token);
                    i = end;
                }
                None => {
                    emit(Token::Text("["));
                    i += 1;
                }
            },
            b'\\' => {
                emit(Token::Text("\\"));
                i += 1;
            }
            _ => {
                let start = i;
                while i < bytes.len() && !is_special(bytes[i]) {
                    i += 1;
                }
                emit(Token::Text(&s[start..i]));
            }
        }
    }
}

/// What the search for the rest of a link, `](url)`, found. It is kept between the `[` of a
/// block, which would otherwise each search the same bytes again.
enum LinkTail {
    /// Not searched yet.
    Unknown,
    /// There is no `](` with a `)` after it in the rest of the block.
    Never,
    /// The first `](` after the position the search started from is at `close`, and the first
    /// `)` after that is at `end`.
    Found {
        close: usize,
        end: usize,
        /// The last `\n` between the start of the search and `close`.
        last_newline: Option<usize>,
        url_ok: bool,
    },
}

impl LinkTail {
    fn search(s: &str, from: usize) -> LinkTail {
        let found = s[from..].find("](").and_then(|n| {
            let close = from + n;
            let end = close + 2 + s[close + 2..].find(')')?;
            Some((close, end))
        });
        match found {
            Some((close, end)) => LinkTail::Found {
                close,
                end,
                last_newline: memrchr(b'\n', &s.as_bytes()[from..close]).map(|n| from + n),
                url_ok: !s[close + 2..end].contains(char::is_whitespace),
            },
            None => LinkTail::Never,
        }
    }

    /// Parses `[text](url)` at the `[` at `start`. Returns the token and the position after it.
    /// Calls have to come with rising `start`.
    fn link_at<'a>(&mut self, s: &'a str, start: usize) -> Option<(Token<'a>, usize)> {
        let stale = match *self {
            LinkTail::Unknown => true,
            LinkTail::Never => false,
            LinkTail::Found { close, .. } => close < start,
        };
        if stale {
            *self = LinkTail::search(s, start);
        }
        match *self {
            LinkTail::Found { close, end, last_newline, url_ok: true }
                if start + 1 < close && last_newline.map_or(true, |n| n < start) =>
            {
                let token = Token::Link { text: &s[start + 1..close], url: &s[close + 2..end] };
                Some((token, end + 1))
            }
            _ => None,
        }
    }
}

fn render_inline(s: &str, out: &mut String) {
    lex_each(s, |token| match token {
        Token::Text(text) => escape_html(text, out),
        Token::Emph(text) => {
            out.push_str("<em>");
            escape_html(text, out);
            out.push_str("</em>");
        }
        Token::Code(text) => {
            out.push_str("<code>");
            escape_html(text, out);
            out.push_str("</code>");
        }
        Token::Link { text, url } => {
            out.push_str("<a href=\"");
            escape_html(url, out);
            out.push_str("\">");
            escape_html(text, out);
            out.push_str("</a>");
        }
    });
}

fn entity(b: u8) -> Option<&'static str> {
    match b {
        b'&' => Some("&amp;"),
        b'<' => Some("&lt;"),
        b'>' => Some("&gt;"),
        b'"' => Some("&quot;"),
        _ => None,
    }
}

/// Appends `s` to `out` with `&`, `<`, `>` and `"` replaced by their entities.
fn escape_html(s: &str, out: &mut String) {
    let mut start = 0;
    for (i, &b) in s.as_bytes().iter().enumerate() {
        if let Some(entity) = entity(b) {
            out.push_str(&s[start..i]);
            out.push_str(entity);
            start = i + 1;
        }
    }
    out.push_str(&s[start..]);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lexes_text_and_emphasis() {
        assert_eq!(
            lex("a *b* c"),
            vec![
                Token::Text("a "),
                Token::Emph("b"),
                Token::Text(" c")
            ]
        );
    }

    #[test]
    fn blocks_are_split_at_blank_lines() {
        assert_eq!(split_blocks("a\nb\n\n\nc\n"), vec!["a\nb", "c"]);
    }
}
