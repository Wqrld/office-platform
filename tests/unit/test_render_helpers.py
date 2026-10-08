import pytest

import render


def test_pod_specs_every_shape():
    pod = {"containers": [{"name": "c"}]}
    objs = [
        {"kind": "Deployment", "spec": {"replicas": 3, "template": {"spec": pod}}},
        {"kind": "StatefulSet", "spec": {"template": {"spec": pod}}},
        {"kind": "CronJob", "spec": {"jobTemplate": {"spec": {"template": {"spec": pod}}}}},
        {"kind": "Pod", "spec": pod},
        {"kind": "Service", "spec": {"ports": []}},
        {"kind": "ExternalSecret", "spec": {"template": {"type": "Opaque"}}},   # not a pod template
        {"kind": "ConfigMap"},
    ]
    assert [(d["kind"], p, n) for d, p, n in render.pod_specs(objs)] == [
        ("Deployment", pod, 3), ("StatefulSet", pod, 1), ("CronJob", pod, 1), ("Pod", pod, 1)]


def test_org_values_cluster_yaml_bare_and_empty(tmp_path):
    cluster = tmp_path / "cluster.yaml"
    cluster.write_text("kind: FluxInstance\n---\nkind: HelmRelease\nspec:\n  values: {domain: x.org}\n")
    assert render.org_values(cluster) == {"domain": "x.org"}
    bare = tmp_path / "values.yaml"
    bare.write_text("# a comment\ndomain: y.org\nsize: small\n")
    assert render.org_values(bare) == {"domain": "y.org", "size": "small"}
    empty = tmp_path / "empty.yaml"
    empty.write_text("# nothing\n")
    assert render.org_values(empty) == {}


def test_org_values_of_the_example():
    values = render.org_values(render.ROOT / "examples" / "cluster.yaml")
    assert "domain" in values and "apps" in values


def test_yaml_file_round_trips_and_is_removed():
    with render.yaml_file({"a": [1, "${X}"]}) as f:
        assert render.load(f.read_text()) == {"a": [1, "${X}"]}
    assert not f.exists()


def test_yaml_file_removed_on_error():
    with pytest.raises(RuntimeError), render.yaml_file({}) as f:
        raise RuntimeError
    assert not f.exists()


def test_report(capsys):
    assert render.report([], "all good") == 0
    assert capsys.readouterr().out == "\nOK — all good\n"
    assert render.report(["one", "two"], "all good", "thing(s)") == 1
    assert capsys.readouterr().out == "\n   one\n   two\n\nFAIL — 2 thing(s)\n"


def test_install_file():
    env = {"DOMAIN": "o.example.org", "ACME_EMAIL": "a@b.c", "GATEWAY_IP": "10.0.0.5", "INSTALL": "true",
           "STORAGE_CLASS": "local-path", "LB_KIND": "metallb", "SOURCE_URL": "https://git.example/x",
           "SOURCE_SECRET": "key", "VERSION": "9.9.9"}
    flux, git, hr = render.install_file(env)
    assert flux["kind"] == "FluxInstance"
    assert git["spec"]["url"] == "https://git.example/x" and git["spec"]["ref"] == {"tag": "v9.9.9"}
    assert git["spec"]["secretRef"] == {"name": "key"}
    v = hr["spec"]["values"]
    assert (v["domain"], v["size"], v["smtp"]) == ("o.example.org", "small", {"configured": False})
    assert v["cluster"]["loadBalancer"] == {"kind": "metallb", "install": True, "pool": ["10.0.0.5/32"]}
    assert v["source"] == {"url": "https://git.example/x", "secretRef": "key"}
    assert "secretRef" not in render.install_file(env | {"SOURCE_SECRET": ""})[1]["spec"]
