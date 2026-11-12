# skills

Agent skills (Claude Code / claude.ai). Each directory is one skill, with its `SKILL.md`
at the top.

- [`sansio-readability`](sansio-readability/SKILL.md): makes a sans-IO Rust crate's state
  machine easier to read without changing its behaviour. It maps the states, inputs, outputs
  and timers, refactors in small checked steps (with an optional old-vs-new differential
  harness), and summarizes. `evals/` holds the test prompts and assertions used to
  develop it.
- [`rust-perf-optimization`](rust-perf-optimization/SKILL.md): measured performance work on
  a Rust crate. It records a baseline with instruction counts and output hashes, profiles down
  to source lines and allocation sites, prototypes one candidate at a time, tries to refute
  each win with adversarial inputs, and reports gains, costs and negative results. Bundles
  scripts for callgrind A/B runs, per-line callgrind summaries, DHAT summaries and
  alternating wall-clock timing.

## Install

With the [skills CLI](https://github.com/vercel-labs/skills), which works for Claude Code,
Codex, Cursor, opencode and other agents:

```sh
npx skills add FalkWoldmann/skills@sansio-readability
```

Add `-g` to install it for your user instead of the current project.

With [Symposium](https://github.com/symposium-dev/symposium), add this repo as a plugin
source and enable the skill in your workspace with `cargo agents use sansio-readability`.

You can also copy the skill's directory into your agent's skills folder, e.g.
`~/.claude/skills/`.

## License

Licensed under either of [Apache License, Version 2.0](LICENSE-APACHE) or
[MIT license](LICENSE-MIT) at your option.
