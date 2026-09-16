# Pre-port fixtures

The hand-written manifests Docs ran on **before** it moved onto the platform charts, frozen
at their last commit:

    git show 9e60594^:apps/docs/{datastores,secrets,routes}.yaml

They are 271 lines and they are not live anywhere. They are here so
`tests/equivalence.py` stays runnable: `9e60594` deleted the originals from the `config`
repo, which left the equivalence check pointing at files that no longer exist — it had
become a claim in `PROGRESS.md` rather than a test.

## What they prove that the golden files do not

A golden file answers *"did our output change?"*. These answer *"does our output still
match what the cluster had before the port?"* — the question that made adopting the live
objects a no-op, with identical UIDs and nothing recreated.

That guarantee has a shelf life. When a chart change is *meant* to alter one of these
objects, the honest move is to delete the affected case from `tests/equivalence.sh` and say
so in the commit — not to re-freeze the fixture from the new output, which would assert
only that the chart equals itself.

Do not edit these files. They are history.
