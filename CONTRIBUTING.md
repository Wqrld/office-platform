# Contributing

## Checks

Everything CI runs is a script you can run locally; `AGENTS.md` (Checks) lists what each one
answers. `tests/toolchain.sh <tool…>` installs the pinned versions of helm, flux,
kubeconform, conftest, dyff and gitleaks; the scripts also need Python 3 with PyYAML.

```sh
./tests/schema.py && ./tests/golden.py          # charts
./tests/build.py built && ./tests/kubeconform.sh tests/golden built
./tests/binding.py && ./tests/check-secrets.py && ./tests/profiles.py   # need network
conftest verify --policy policy/charts && conftest verify --policy policy/config
```

A change to a template or to `tests/cases/` changes a golden: run `./tests/golden.py --update`
and commit the diff with the change, after reading it. A new app needs a case in
`tests/cases/index.yaml` for each of its platform releases.

## One change at a time

- **A refactor changes no output.** `./tests/golden.py` matches and `./tests/render-diff.sh`
  ends with "No change to what any cluster applies". If either moves, the change is not a
  refactor: split it out and give it a `CHANGELOG.md` line under `## Unreleased`.
- **One theme per pull request**, so each diff can be reviewed on its own.
- **Comments say why, once.** A reason that applies to several files goes in one README or
  ADR, and each file links to it in at most one line. Keep what is non-obvious about an
  upstream chart, image or protocol; cut history, what the next line already says, and the
  same paragraph pasted into every app.
- `docs/history/` and the ADR bodies record decisions as they were made: leave them alone.

## Commits

`<gitmoji> (<scope>) <subject in the imperative>`, enforced by `.gitlint` on every pull
request:

```
✨ (drive) document thumbnails
🐛 (valkey) let projects run INFO
```

Title at most 80 characters, body wrapped at 92.

## Decisions

A change that reverses or adds a design decision comes with an ADR in `docs/adr/`.
