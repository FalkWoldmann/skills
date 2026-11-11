use std::io::{self, Read, Write};
use std::process::ExitCode;

fn main() -> ExitCode {
    let mut input = String::new();
    let result = match std::env::args().nth(1) {
        Some(path) => std::fs::read_to_string(&path).map(|s| input = s),
        None => io::stdin().read_to_string(&mut input).map(|_| ()),
    };
    if let Err(err) = result {
        eprintln!("litemark: {err}");
        return ExitCode::FAILURE;
    }
    let html = litemark::to_html(&input);
    match io::stdout().write_all(html.as_bytes()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(_) => ExitCode::FAILURE,
    }
}
