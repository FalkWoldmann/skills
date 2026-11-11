//! litemark: a small inline markup to HTML converter.
//!
//! Blocks are separated by blank lines. A block that starts with `# ` is a heading and gets
//! an id made from its text; every other block is a paragraph. Inside a block, `*text*` is
//! emphasis, `` `text` `` is code and `[text](url)` is a link. A backslash before one of the
//! special characters makes it literal.

use std::collections::HashMap;

use memchr::memchr;

/// Bytes that can start an inline construct.
const SPECIALS: &[u8] = b"*`[\\";

#[derive(Debug, PartialEq)]
pub(crate) enum Token {
    Text(String),
    Emph(String),
    Code(String),
    Link { text: String, url: String },
}

/// Converts `input` to HTML.
pub fn to_html(input: &str) -> String {
    let mut out = String::new();
    let mut ids: HashMap<String, usize> = HashMap::new();
    for block in split_blocks(input) {
        match block.strip_prefix("# ") {
            Some(title) => {
                let id = unique_id(&mut ids, title);
                out.push_str(&format!("<h1 id=\"{}\">", id));
                render_inline(title, &mut out);
                out.push_str("</h1>\n");
            }
            None => {
                out.push_str("<p>");
                render_inline(&block, &mut out);
                out.push_str("</p>\n");
            }
        }
    }
    out
}

/// Splits the input into blocks at blank lines. Lines inside a block are joined with `\n`,
/// and a `\r` before the line end is dropped.
fn split_blocks(input: &str) -> Vec<String> {
    let mut blocks = Vec::new();
    let mut current = String::new();
    let mut rest = input;
    while !rest.is_empty() {
        let (line, tail) = match memchr(b'\n', rest.as_bytes()) {
            Some(i) => (&rest[..i], &rest[i + 1..]),
            None => (rest, ""),
        };
        rest = tail;
        let line = line.strip_suffix('\r').unwrap_or(line);
        if line.trim().is_empty() {
            if !current.is_empty() {
                blocks.push(current.clone());
                current = String::new();
            }
        } else {
            if !current.is_empty() {
                current.push('\n');
            }
            current.push_str(line);
        }
    }
    if !current.is_empty() {
        blocks.push(current);
    }
    blocks
}

fn unique_id(ids: &mut HashMap<String, usize>, title: &str) -> String {
    let mut slug = String::new();
    for ch in title.chars() {
        if ch.is_alphanumeric() {
            slug.push_str(&ch.to_lowercase().to_string());
        } else if !slug.ends_with('-') {
            slug.push('-');
        }
    }
    let slug = slug.trim_matches('-').to_string();
    let seen = ids.entry(slug.clone()).or_insert(0);
    *seen += 1;
    if *seen == 1 {
        slug
    } else {
        format!("{}-{}", slug, *seen - 1)
    }
}

fn is_special(b: u8) -> bool {
    SPECIALS.contains(&b)
}

pub(crate) fn lex(s: &str) -> Vec<Token> {
    let bytes = s.as_bytes();
    let mut tokens = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'\\' if i + 1 < bytes.len() && is_special(bytes[i + 1]) => {
                tokens.push(Token::Text(s[i + 1..i + 2].to_string()));
                i += 2;
            }
            b'*' => match memchr(b'*', &bytes[i + 1..]) {
                Some(len) if len > 0 => {
                    tokens.push(Token::Emph(s[i + 1..i + 1 + len].to_string()));
                    i += len + 2;
                }
                _ => {
                    tokens.push(Token::Text("*".to_string()));
                    i += 1;
                }
            },
            b'`' => match memchr(b'`', &bytes[i + 1..]) {
                Some(len) if len > 0 => {
                    tokens.push(Token::Code(s[i + 1..i + 1 + len].to_string()));
                    i += len + 2;
                }
                _ => {
                    tokens.push(Token::Text("`".to_string()));
                    i += 1;
                }
            },
            b'[' => match lex_link(&s[i..]) {
                Some((token, len)) => {
                    tokens.push(token);
                    i += len;
                }
                None => {
                    tokens.push(Token::Text("[".to_string()));
                    i += 1;
                }
            },
            b'\\' => {
                tokens.push(Token::Text("\\".to_string()));
                i += 1;
            }
            _ => {
                let start = i;
                while i < bytes.len() && !is_special(bytes[i]) {
                    i += 1;
                }
                tokens.push(Token::Text(s[start..i].to_string()));
            }
        }
    }
    tokens
}

/// Parses `[text](url)` at the start of `s`. Returns the token and the bytes it covers.
fn lex_link(s: &str) -> Option<(Token, usize)> {
    let close = s.find("](")?;
    let end = close + 2 + s[close + 2..].find(')')?;
    let text = &s[1..close];
    let url = &s[close + 2..end];
    if text.is_empty() || text.contains('\n') || url.contains(char::is_whitespace) {
        return None;
    }
    Some((
        Token::Link {
            text: text.to_string(),
            url: url.to_string(),
        },
        end + 1,
    ))
}

fn render_inline(s: &str, out: &mut String) {
    for token in lex(s) {
        match token {
            Token::Text(text) => out.push_str(&escape_html(&text)),
            Token::Emph(text) => out.push_str(&format!("<em>{}</em>", escape_html(&text))),
            Token::Code(text) => out.push_str(&format!("<code>{}</code>", escape_html(&text))),
            Token::Link { text, url } => out.push_str(&format!(
                "<a href=\"{}\">{}</a>",
                escape_html(&url),
                escape_html(&text)
            )),
        }
    }
}

fn escape_html(s: &str) -> String {
    let mut out = String::new();
    for ch in s.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            _ => out.push_str(&ch.to_string()),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lexes_text_and_emphasis() {
        assert_eq!(
            lex("a *b* c"),
            vec![
                Token::Text("a ".into()),
                Token::Emph("b".into()),
                Token::Text(" c".into())
            ]
        );
    }

    #[test]
    fn blocks_are_split_at_blank_lines() {
        assert_eq!(split_blocks("a\nb\n\n\nc\n"), vec!["a\nb", "c"]);
    }
}
