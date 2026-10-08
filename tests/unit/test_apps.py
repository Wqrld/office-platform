"""Static checks on apps/ that need no render."""
import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
APPS = sorted(k.parent for k in (ROOT / "apps").glob("*/kustomization.yaml"))
SIZES = ("small", "medium", "large")


# Every app writes the same `<app>-sizes` generator out by hand: a kustomize Component cannot
# carry it, because the ConfigMap's name and namespace are the app's and a Component cannot
# be parameterised. So the copies are held uniform here instead.
@pytest.mark.parametrize("app", APPS, ids=lambda a: a.name)
def test_sizes_generator_is_uniform(app):
    k = yaml.safe_load((app / "kustomization.yaml").read_text())
    gen = [g for g in k.get("configMapGenerator", []) if g["name"] == f"{app.name}-sizes"]
    assert len(gen) == 1, "one `<app>-sizes` configMapGenerator"
    gen = gen[0]
    assert gen["namespace"] == f"office-{app.name}"
    assert gen["options"] == {"disableNameSuffixHash": True,
                              "labels": {"reconcile.fluxcd.io/watch": "Enabled"}}
    files = dict(f.split("=", 1) for f in gen["files"])
    want = {s: f"sizes/{s}.yaml" for s in SIZES}
    if any(key.startswith("platform-") for key in files):
        want |= {"platform-small": "../sizes-no-pdb.yaml", "platform-medium": "../sizes-no-pdb.yaml",
                 "platform-large": "sizes/platform-large.yaml"}
    # A second release's sizes (LiveKit's egress) come as a whole `<release>-<size>` set.
    extra = {key.rsplit("-", 1)[0] for key in files.keys() - want.keys()}
    want |= {f"{r}-{s}": f"sizes/{r}-{s}.yaml" for r in extra for s in SIZES}
    assert files == want
    on_disk = {f"sizes/{p.name}" for p in (app / "sizes").glob("*.yaml")}
    assert on_disk == {f for f in files.values() if f.startswith("sizes/")}, "a size file nothing reads"
