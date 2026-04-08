# Contributing guide

Thank you for your interest in contributing to `stealth-message`.
Please read this guide before opening an issue or submitting a pull request.

---

## Before you start

1. Read the [README](README.md) to understand what the project is.
2. Read [ARCHITECTURE.md](ARCHITECTURE.md) to understand the structure and design decisions.
3. Read [SECURITY.md](SECURITY.md) to know the security policy.
4. Read `docs/protocol.md` — it is the source of truth for the protocol.
5. Read the `CLAUDE.md` of the sub-project you are going to work on.

---

## Reporting bugs

- Use **GitHub Issues** to report bugs.
- **Exception:** if the bug is a security vulnerability, follow the instructions in
  [SECURITY.md](SECURITY.md) and **do not open a public issue**.
- Before opening an issue, check whether a similar one already exists.
- Include: description, steps to reproduce, expected vs actual result,
  OS version and affected sub-project version.

---

## Proposing improvements

- Open an **Issue** describing the improvement before implementing it.
- Explain the problem it solves and why the proposed solution is the right one.
- For large changes or changes that affect the protocol, wait for feedback before writing code.

---

## Contribution process

### 1. Working branch

**All work is done on the `test` branch. Never commit directly to `main`.**
`main` only receives changes via Pull Request from `test`.

```bash
git clone https://github.com/<your-username>/stealth-message.git
cd stealth-message
git checkout test
```

### 2. Protocol changes

If your contribution involves a change to the communication protocol:

1. **Update `docs/protocol.md` first.** The document is the source of truth.
2. Describe the change, its motivation, and its impact on all four sub-projects.
3. Update all affected sub-projects in the same PR.

### 3. Code

- Follow the conventions of the sub-project (see its `CLAUDE.md`).
- Write tests for new logic, especially in `crypto/` and `network/` modules.
- `crypto/` and `network/` modules require tests before any merge (TDD).
- Never put sensitive information (keys, passphrases) in tests or configuration.

### 4. CHANGELOG

**Required:** update `CHANGELOG.md` under the `[Unreleased]` section with an entry
describing your change. Use the categories from [Keep a Changelog](https://keepachangelog.com/en/1.0.0/):

- `Added` — new functionality
- `Changed` — change to existing functionality
- `Deprecated` — functionality that will be removed in the future
- `Removed` — removed functionality
- `Fixed` — bug fix
- `Security` — security-related fix

### 5. Pull request

- Short and descriptive title in English.
- Describe **what** changes and **why**.
- If it closes an issue: `Closes #<number>`.
- PRs that affect the protocol must document the impact on all four sub-projects.
- A PR must have a clear scope; avoid mixing features with unrelated refactors.

---

## Code standards by sub-project

| Sub-project | Language | Formatter    | Linter | Types   |
|-------------|----------|--------------|--------|---------|
| `cli/`      | Python   | `black`      | `ruff` | `mypy`  |
| `linux/`    | Python   | `black`      | `ruff` | `mypy`  |
| `macos/`    | Swift    | swift-format | SwiftLint | — |
| `windows/`  | C#       | `dotnet format` | Roslyn analyzers | Nullable enable |

---

## Merge policy

- At least **1 review** is required before merging.
- Tests must pass in CI.
- No merging code with hardcoded secrets, keys, or passphrases.
- Protocol changes require explicit review from the maintainers.

---

## Code of conduct

This project follows the principle of respectful and constructive collaboration.
Contributions are evaluated on their technical merit. Direct, honest, and
professional communication is expected.
