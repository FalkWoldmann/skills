use std::time::Instant;

fn main() {
    let corpus = std::fs::read_to_string("bench/corpus.txt")
        .expect("run `python3 scripts/gen-corpus.py > bench/corpus.txt` first");
    let mut times = Vec::new();
    for _ in 0..15 {
        let start = Instant::now();
        let html = litemark::to_html(&corpus);
        times.push(start.elapsed());
        std::hint::black_box(html);
    }
    times.sort();
    println!("corpus: {} bytes, median {:?}", corpus.len(), times[times.len() / 2]);
}
