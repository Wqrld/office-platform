# Values that must be REJECTED

One file per way of getting a values file wrong. Each is fed to `helm template` on its own —
chart defaults are valid, so the only thing that can fail is the thing the file is named
after — and `tests/schema.py` asserts the render fails *and* that the error says what the
`# expect:` line says.

Both halves matter. A schema that has only ever seen valid input is indistinguishable from
an absent one: `values.schema.json` is the single check standing between a typo'd key and a
release where that key silently does nothing, and nothing else in this repo would notice it
had stopped working.

Format: the first line is `# expect: <substring of the expected error>`. Everything else is
values.
