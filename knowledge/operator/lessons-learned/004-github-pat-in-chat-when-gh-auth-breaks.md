# Lesson — When `gh` Auth Breaks Mid-Environment, a Chat-Pasted PAT Is Kelvin's Explicit Fallback, Not a Security Incident

**Date:** 2026-09-15
**Phase:** IaC diagnosis domains + resource-health monitoring build — push/deploy step

## What Was Found

`git push origin master` failed repeatedly in this environment with
`fatal: could not read Username for 'https://github.com'` — traced to a
stale `gh` CLI (v2.4.0, no `gh auth token` subcommand) whose credential
helper (`gh auth git-credential get`) silently exits 1 with no output,
even though `gh auth status` reported a valid logged-in session. Neither
`GH_TOKEN`/`GITHUB_TOKEN` env vars nor a working credential helper were
available anywhere in the shell.

Kelvin's response was to paste a live GitHub PAT directly in chat and say
to use it. The default instinct here is caution — a raw credential in
plaintext chat looks like exactly the kind of thing to flag and
recommend rotating. Kelvin pushed back explicitly: he is the sole viewer
of this session, there is no security risk from his perspective, and he
wants the token used going forward without the caution being repeated
each time.

## Why It Matters

- A credential-handling instinct that's correct by default (flag
  plaintext-pasted secrets, recommend rotation) can still be the wrong
  call once the person who owns the credential has explicitly weighed
  the tradeoff and made a different choice about their own risk. The
  right move after one clear advisory is to comply and stop repeating
  it — not to keep re-litigating a decision that was already made.
- There's a real distinction between *using* a credential ephemerally
  (env var scoped to one shell command, unset immediately after, never
  written to `.git/config`/`.netrc`/any file) and *persisting* it
  somewhere durable. Kelvin asked for the latter too ("keep this in
  memory and use it going forward") — that's a different, bigger ask
  than "use it this once," and the honest answer is that Claude's memory
  system is plaintext markdown files with no encryption, not a secrets
  manager, so a live PAT doesn't belong there regardless of how the
  ephemeral-use question was already resolved. The better fix for
  genuine cross-session persistence is fixing `gh auth login` once in
  the environment, which stores credentials the way `gh` is actually
  built to store them.

## Proof

Verified after each push that the token never landed in `.git/config`
(`grep -i "ghp_\|token" .git/config` → clean) and was `unset` in the same
shell command that used it — the credential helper was inline
(`git -c credential.helper='!f() { echo "username=x-access-token"; echo
"password=$GH_PUSH_TOKEN"; }; f'`), never a persisted helper script.

## What to Watch For Next Time

- Give the security advisory once, clearly, with a concrete alternative
  (rotate the token; here, also: fix `gh auth login`). If the owner of
  the credential explicitly overrides it, comply without repeating the
  advisory — that's their call to make about their own credential.
- Ephemeral use (this session, this push) and durable persistence
  (future sessions, no re-supplying) are different requests with
  different correct answers, even when they arrive in the same breath.
  Saying yes to one doesn't mean saying yes to the other — a plaintext
  memory file is never the right place for a live secret, independent of
  whether using it ephemerally was fine.
- When a CLI tool's auth silently breaks (valid `status`, broken
  `git-credential`), don't assume it's this session's fault or try many
  variations blindly — one targeted diagnostic (call the credential
  helper directly, check its exit code) confirms the tool itself is
  broken, which points at the actual fix (re-run `gh auth login`) rather
  than more workarounds layered on a broken helper.
