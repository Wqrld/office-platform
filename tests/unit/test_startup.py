import pytest

import startup


@pytest.mark.parametrize("ref, want", [
    ("nginx:1.27", ("registry-1.docker.io", "library/nginx", "1.27")),
    ("nginx", ("registry-1.docker.io", "library/nginx", "latest")),
    ("bitnami/valkey:8", ("registry-1.docker.io", "bitnami/valkey", "8")),
    ("docker.io/library/redis:7", ("registry-1.docker.io", "library/redis", "7")),
    ("docker.io/collabora/code:24", ("registry-1.docker.io", "collabora/code", "24")),
    ("ghcr.io/a/b:1.0", ("ghcr.io", "a/b", "1.0")),
    ("localhost/x:1", ("localhost", "x", "1")),
    ("registry.local:5000/team/app", ("registry.local:5000", "team/app", "latest")),
    ("ghcr.io/a/b:1.0@sha256:abc", ("ghcr.io", "a/b", "sha256:abc")),
])
def test_split(ref, want):
    assert startup._split(ref) == want


def test_needs_skips_optional_and_reads_every_source():
    pod = {
        "volumes": [
            {"secret": {"secretName": "s-vol"}},
            {"secret": {"secretName": "s-opt", "optional": True}},
            {"configMap": {"name": "cm-vol"}},
            {"projected": {"sources": [{"secret": {"name": "s-proj"}},
                                       {"configMap": {"name": "cm-opt", "optional": True}}]}},
            {"emptyDir": {}},
        ],
        "initContainers": [{"envFrom": [{"secretRef": {"name": "s-init"}}]}],
        "containers": [{
            "envFrom": [{"configMapRef": {"name": "cm-env"}},
                        {"secretRef": {"name": "s-env-opt", "optional": True}}],
            "env": [{"name": "A", "valueFrom": {"secretKeyRef": {"name": "s-key", "key": "k"}}},
                    {"name": "B", "valueFrom": {"configMapKeyRef": {"name": "cm-key", "key": "k"}}},
                    {"name": "C", "value": "plain"}],
        }],
    }
    assert startup.needs(pod) == {
        ("Secret", "s-vol"), ("ConfigMap", "cm-vol"), ("Secret", "s-proj"), ("Secret", "s-init"),
        ("ConfigMap", "cm-env"), ("Secret", "s-key"), ("ConfigMap", "cm-key")}


@pytest.mark.parametrize("obj, want", [
    ({"kind": "Secret", "metadata": {"name": "a"}}, {("Secret", "a")}),
    ({"kind": "ConfigMap", "metadata": {"name": "a"}}, {("ConfigMap", "a")}),
    ({"kind": "ExternalSecret", "metadata": {"name": "a"}, "spec": {}}, {("Secret", "a")}),
    ({"kind": "ExternalSecret", "metadata": {"name": "a"}, "spec": {"target": {"name": "b"}}},
     {("Secret", "b")}),
    ({"kind": "Certificate", "metadata": {"name": "a"}, "spec": {"secretName": "tls"}}, {("Secret", "tls")}),
    ({"kind": "GarageKey", "metadata": {"name": "a"}, "spec": {}}, {("Secret", "a")}),
    ({"kind": "GarageKey", "metadata": {"name": "a"}, "spec": {"secretTemplate": {"name": "b"}}},
     {("Secret", "b")}),
    ({"kind": "Deployment", "metadata": {"name": "a"}, "spec": {}}, set()),
    # A Job's Role creates the Secret at run time: the names it may read are what it makes.
    ({"kind": "Role", "metadata": {"name": "j"}, "rules": [
        {"apiGroups": [""], "resources": ["secrets"], "verbs": ["create"]},
        {"apiGroups": [""], "resources": ["secrets"], "resourceNames": ["keys"], "verbs": ["get"]}]},
     {("Secret", "keys")}),
    ({"kind": "Role", "metadata": {"name": "r"}, "rules": [
        {"apiGroups": [""], "resources": ["secrets"], "resourceNames": ["x"], "verbs": ["get"]}]},
     set()),
])
def test_produces(obj, want):
    assert startup.produces(obj) == want
