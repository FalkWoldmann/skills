#!/usr/bin/env python3
"""Scaffold an old-vs-new differential harness for a sans-IO crate.

usage: difftest_scaffold.py --repo REPO --package NAME --out DIR --base REV

Creates, outside the repo:
  DIR/orig/     the whole repo at REV, with every local package (workspace
                members and other path dependencies inside the repo) renamed
                to <name>-orig, so both copies fit in one lockfile. Library
                names are pinned, so module paths and CARGO_CRATE_NAME stay
                as they were; CARGO_PKG_NAME does change.
  DIR/harness/  a detached bin crate depending on both:
                  orig = { package = "NAME-orig", path = ... }   (the base)
                  new  = { package = "NAME",      path = ... }   (the working tree)
                every feature of NAME forwarded to both, the workspace's
                Cargo.lock copied in so dependency versions match, and
                src/main.rs from the template, to be filled in.

REV is the base commit you noted before the first edit. If you started on
top of uncommitted changes, pass `--base $(git stash create)`, which records
them as a commit without touching the working tree.

Then, from DIR/harness:  cargo run --release -- <cases> [seed]
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "difftest_main.rs"


def metadata(cwd, no_deps=True):
    cmd = ["cargo", "metadata", "--format-version", "1"]
    if no_deps:
        cmd.append("--no-deps")
    run = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if run.returncode != 0:
        sys.exit(f"`{' '.join(cmd)}` failed in {cwd}; fix the workspace first:\n{run.stderr}")
    return json.loads(run.stdout)


def sections(lines):
    """Yield (index, header) for each line, header being the current [table]
    name with comments stripped."""
    header = ""
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("["):
            header = s.split("#", 1)[0].strip()
        yield i, header


def rename_package(manifest, old, new, lib_name):
    lines = manifest.read_text().splitlines(keepends=True)
    renamed = False
    has_lib_name = False
    for i, header in sections(lines):
        s = lines[i].strip()
        if header == "[package]" and not renamed:
            if re.match(r"name\s*=\s*([\"'])" + re.escape(old) + r"\1", s):
                lines[i] = re.sub(r"([\"'])" + re.escape(old) + r"\1", f'"{new}"', lines[i], count=1)
                renamed = True
        if header == "[lib]" and re.match(r"name\s*=", s):
            has_lib_name = True
    if not renamed:
        sys.exit(f'could not find name = "{old}" under [package] in {manifest}')
    text = "".join(lines)
    if not has_lib_name:
        # Keep the library's crate name, so module_path!() and
        # CARGO_CRATE_NAME match the working tree's.
        if re.search(r"^\[lib\]", text, re.M):
            text = re.sub(r"^(\[lib\][^\n]*\n)", r'\1name = "' + lib_name + '"\n', text, count=1, flags=re.M)
        else:
            text = text.rstrip("\n") + f'\n\n[lib]\nname = "{lib_name}"\n'
    manifest.write_text(text)


def point_deps_at_renamed(manifest, names):
    """Make dependencies on renamed packages keep their key but name the
    renamed package: `foo = { path = ".." }` becomes
    `foo = { package = "foo-orig", path = ".." }`."""
    text = manifest.read_text()
    for name in names:
        q = re.escape(name)
        key = r'(?:"' + q + r'"|' + q + r")"
        # Existing `package = "foo"` (renamed dependencies, workspace deps).
        text = re.sub(r"(\bpackage\s*=\s*)([\"'])" + q + r"\2", r'\1"' + name + '-orig"', text)
        # Inline tables without a package key.
        text = re.sub(
            r"^(\s*" + key + r"\s*=\s*\{)(?![^}\n]*\bpackage\s*=)",
            r'\1 package = "' + name + '-orig",',
            text,
            flags=re.M,
        )
        # Dotted keys: `foo.path = ".."` or `foo.workspace = true`.
        if not re.search(r"^\s*" + key + r"\.package\s*=", text, re.M):
            text = re.sub(
                r"^(\s*)(" + key + r")\.(path|workspace)\s*=",
                lambda m: f'{m[1]}{m[2]}.package = "{name}-orig"\n{m[0]}',
                text,
                count=1,
                flags=re.M,
            )

        # [dependencies.foo], [target.'cfg(..)'.dev-dependencies.foo], ...
        def table(m, text=text):
            rest = text[m.end():]
            nxt = re.search(r"^\[", rest, re.M)
            body = rest[: nxt.start()] if nxt else rest
            if re.search(r"^\s*package\s*=", body, re.M):
                return m[0]
            return m[0] + f'package = "{name}-orig"\n'

        text = re.sub(r"^\[[^\]\n]*\bdependencies\." + key + r"\][^\n]*\n", table, text, flags=re.M)
    manifest.write_text(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--package", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", required=True, help="the base commit noted before the first edit")
    a = ap.parse_args()

    repo = Path(a.repo).resolve()
    out = Path(a.out).resolve()
    if repo in out.parents or out == repo:
        sys.exit("--out must be outside the repo, so the harness never shows up in its diff")
    git_root = Path(
        subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=repo, text=True).strip()
    )

    meta = metadata(repo)
    pkgs = [p for p in meta["packages"] if p["name"] == a.package]
    if not pkgs:
        sys.exit(f"no package {a.package!r} in {repo}")
    pkg = pkgs[0]
    new_dir = Path(pkg["manifest_path"]).parent
    rel = new_dir.relative_to(git_root)
    features = sorted(f for f in pkg["features"] if f != "default")
    if not any(k in ("lib", "rlib") for t in pkg["targets"] for k in t["kind"]):
        sys.exit(f"{a.package} has no library target to drive")

    # Every package that lives in the repo: members, and path dependencies
    # inside it that aren't members (vendored crates). Each would otherwise
    # appear twice under one name and version.
    full = metadata(repo, no_deps=False)
    local = {}
    for p in full["packages"]:
        manifest = Path(p["manifest_path"])
        if p["source"] is None and git_root in manifest.parents:
            lib = [t["name"] for t in p["targets"] if any(k in ("lib", "rlib") for k in t["kind"])]
            local[p["name"]] = (manifest.relative_to(git_root), (lib or [p["name"].replace("-", "_")])[0])

    orig_root = out / "orig"
    if orig_root.exists():
        shutil.rmtree(orig_root)
    orig_root.mkdir(parents=True)
    archive = subprocess.Popen(["git", "archive", a.base], cwd=git_root, stdout=subprocess.PIPE)
    subprocess.check_call(["tar", "-x", "-C", str(orig_root)], stdin=archive.stdout)
    if archive.wait() != 0:
        sys.exit(f"git archive {a.base} failed")
    orig_dir = orig_root / rel

    manifests = set()
    for name, (manifest, lib_name) in local.items():
        target = orig_root / manifest
        if target.exists():  # a package added after the base has no original
            rename_package(target, name, name + "-orig", lib_name)
            manifests.add(target)
    root_manifest = orig_root / Path(meta["workspace_root"]).relative_to(git_root) / "Cargo.toml"
    if root_manifest.exists():
        manifests.add(root_manifest)
    for manifest in manifests:
        point_deps_at_renamed(manifest, local)

    harness = out / "harness"
    (harness / "src").mkdir(parents=True, exist_ok=True)
    feature_lines = "\n".join(f'{f} = ["orig/{f}", "new/{f}"]' for f in features)
    default_line = 'default = ["orig/default", "new/default"]' if "default" in pkg["features"] else ""
    (harness / "Cargo.toml").write_text(
        f"""[package]
name = "difftest"
version = "0.0.0"
edition = "{pkg["edition"]}"
publish = false

# Not part of any workspace above it.
[workspace]

[dependencies]
orig = {{ package = "{a.package}-orig", path = "{orig_dir}", default-features = false }}
new = {{ package = "{a.package}", path = "{new_dir}", default-features = false }}

[features]
{default_line}
{feature_lines}

[profile.release]
debug-assertions = true
overflow-checks = true
"""
    )
    lock = Path(meta["workspace_root"]) / "Cargo.lock"
    if lock.exists():
        shutil.copy(lock, harness / "Cargo.lock")
    main_rs = harness / "src" / "main.rs"
    if not main_rs.exists():
        main_rs.write_text(TEMPLATE.read_text())

    # Fail here, not at the first build, if a manifest edit was missed.
    check = subprocess.run(
        ["cargo", "metadata", "--format-version", "1", "--manifest-path", str(harness / "Cargo.toml")],
        cwd=harness,
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        sys.exit("the harness manifest doesn't resolve:\n" + check.stderr)

    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    print(f"orig:    {orig_dir}  ({a.package}-orig at {a.base})")
    print(f"new:     {new_dir}  (the working tree)")
    print(f"harness: {harness}")
    print(f"features forwarded: {', '.join(features) or 'none'}")
    if dirty.strip() and a.base == "HEAD":
        print("warning: the working tree has uncommitted changes and --base is HEAD; "
              "if they predate your refactor, use --base $(git stash create)")
    print("next: fill in src/main.rs, then `cargo run --release -- 10000` in the harness")


if __name__ == "__main__":
    main()
