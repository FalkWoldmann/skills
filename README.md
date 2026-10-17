# skills

Agent skills (Claude Code / claude.ai). Each directory is one skill, with its `SKILL.md`
at the top.

- [`sansio-readability`](sansio-readability/SKILL.md): makes a sans-IO Rust crate's state
  machine easier to read without changing its behaviour. It maps the states, inputs, outputs
  and timers, refactors in small checked steps (with an optional old-vs-new differential
  harness), and summarizes. `evals/` holds the test prompts and assertions used to
  develop it.
