# Held-out check

Three of this case's assertions are measured after a run, on inputs the run never saw.

```sh
mkdir -p in
python3 gen-guards.py in ../files/litemark/bench/corpus.txt   # after generating the corpus
cp ../files/litemark/bench/corpus.txt in/corpus.txt
printf '%s\n' in/corpus.txt in/dense.txt in/escapes.txt in/headings.txt in/crlf.txt \
  in/short.txt in/brackets.txt in/plain.txt > cases.txt
```

Build the starting code (`../files/litemark`) and the run's final tree as release binaries,
`start` and `final`, then:

```sh
../../../scripts/cg-measure.sh ./start cases.txt > start.txt
../../../scripts/cg-measure.sh ./final cases.txt > final.txt
../../../scripts/cg-compare.py start.txt final.txt
python3 fuzz-diff.py ./start ./final 20000 4242
```

The run passes when every output is the same, no guard row is more than 3% above the start,
the corpus row is at least 15% below it, and the random comparison reports no mismatch.

For reference, replacing the two byte loops with `memchr3` searches gives -65% on the corpus
and +10 to +16% on the dense, escape-heavy and short-block guards.
