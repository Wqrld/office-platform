# Both directions for every rule in propagation.rego.
package main

import rego.v1

good_route := {
	"kind": "HTTPRoute",
	"metadata": {"name": "docs-api", "labels": {
		"app.kubernetes.io/part-of": "office",
		"app.kubernetes.io/instance": "docs-platform",
	}},
	"spec": {
		"parentRefs": [{"name": "office", "namespace": "office-system", "sectionName": "https"}],
		"hostnames": ["docs.example.org"],
		"rules": [{"backendRefs": [{"name": "docs-backend", "port": 80}]}],
	},
}

route_without(key) := object.union(
	good_route,
	{"spec": object.union(
		object.remove(good_route.spec, {"parentRefs"}),
		{"parentRefs": [object.remove(good_route.spec.parentRefs[0], {key})]},
	)},
)

test_complete_route_passes if {
	count(deny) == 0 with input as good_route
}

# The failure this catches is not a broken route — it is a route that attaches to EVERY
# listener, :80 included, and so quietly answers over plaintext.
test_parentref_without_sectionname_denied if {
	count(deny) > 0 with input as route_without("sectionName")
}

# Without an explicit namespace the ref resolves in the app's own namespace, where there
# is no Gateway at all.
test_parentref_without_namespace_denied if {
	count(deny) > 0 with input as route_without("namespace")
}

test_route_without_parentrefs_denied if {
	count(deny) > 0 with input as object.union(
		good_route,
		{"spec": object.union(object.remove(good_route.spec, {"parentRefs"}), {"parentRefs": []})},
	)
}

test_route_without_hostnames_denied if {
	count(deny) > 0 with input as object.union(
		good_route,
		{"spec": object.union(object.remove(good_route.spec, {"hostnames"}), {"hostnames": []})},
	)
}

# --- label propagation ----------------------------------------------------------------------

# object.union merges RECURSIVELY all the way down, so there is no patch that REMOVES a
# label — the smaller map just merges back into the bigger one. Build the object outright.
route_without_label(label) := {
	"kind": "HTTPRoute",
	"metadata": {
		"name": "docs-api",
		"labels": object.remove(good_route.metadata.labels, {label}),
	},
	"spec": good_route.spec,
}

test_missing_part_of_denied if {
	count(deny) > 0 with input as route_without_label("app.kubernetes.io/part-of")
}

test_missing_instance_denied if {
	count(deny) > 0 with input as route_without_label("app.kubernetes.io/instance")
}

# --- priority class -------------------------------------------------------------------------

test_deployment_without_priorityclass_denied if {
	count(deny) > 0 with input as {
		"kind": "Deployment",
		"metadata": {"name": "app-media-proxy", "labels": {
			"app.kubernetes.io/part-of": "office",
			"app.kubernetes.io/instance": "app-platform",
		}},
		"spec": {"template": {"spec": {
			"securityContext": {"runAsNonRoot": true, "seccompProfile": {"type": "RuntimeDefault"}},
			"containers": [good_container],
		}}},
	}
}
