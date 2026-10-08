import render


def test_merge_maps_deep_lists_replaced():
    base = {"a": {"x": 1, "y": [1, 2]}, "b": 1}
    over = {"a": {"y": [3]}, "c": 2}
    assert render.merge(base, over) == {"a": {"x": 1, "y": [3]}, "b": 1, "c": 2}
    assert base == {"a": {"x": 1, "y": [1, 2]}, "b": 1}      # inputs untouched


def test_merge_scalar_replaces_map_and_map_replaces_scalar():
    assert render.merge({"a": {"x": 1}}, {"a": None}) == {"a": None}
    assert render.merge({"a": 1}, {"a": {"x": 1}}) == {"a": {"x": 1}}


def test_substitute_known_unknown_and_escape():
    node = {"host": "docs.${DOMAIN}", "other": "${NOPE}", "keycloak": "$${realm}"}
    assert render.substitute(node, {"DOMAIN": "example.org"}) == {
        "host": "docs.example.org", "other": "${NOPE}", "keycloak": "${realm}"}


def test_substitute_whole_value_becomes_yaml():
    assert render.substitute({"dnsNames": "${HOSTS}"}, {"HOSTS": "[a, b]"}) == {"dnsNames": ["a", "b"]}


def test_unresolved():
    objs = [{"a": "${ONE}"}, {"b": ["${TWO}", "$x", "${ONE}"]}]
    assert render.unresolved(objs) == {"ONE", "TWO"}
    assert render.unresolved(objs, {"TWO"}) == {"ONE"}
    assert render.unresolved([{"a": "plain"}]) == set()
