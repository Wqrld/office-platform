# Both directions for every rule in invariants.rego.
#
# 10-verification.md asks for this explicitly, about Kyverno: "a fixture per rule, both
# directions — a pod that should be mutated and one that should be skipped, a PDB that
# should be denied and one that should pass". The reasoning carries over unchanged. A
# policy suite that only ever runs against compliant input is indistinguishable from an
# empty one, and it fails open: the day a template regresses, the rule that was supposed to
# catch it has itself been broken for months and nothing said so.
#
#   conftest verify --policy policy
package main

import rego.v1

# --- helpers ------------------------------------------------------------------------------

good_container := {
	"name": "nginx",
	"image": "docker.io/nginxinc/nginx-unprivileged:1.29-alpine",
	"securityContext": {
		"allowPrivilegeEscalation": false,
		"readOnlyRootFilesystem": true,
		"capabilities": {"drop": ["ALL"]},
	},
	"resources": {
		"requests": {"cpu": "10m", "memory": "32Mi"},
		"limits": {"memory": "128Mi"},
	},
}

deployment(containers) := {
	"kind": "Deployment",
	"metadata": {"name": "app-media-proxy", "labels": {
		"app.kubernetes.io/part-of": "office",
		"app.kubernetes.io/instance": "app-platform",
	}},
	"spec": {"template": {"spec": {
		"priorityClassName": "office-app",
		"securityContext": {"runAsNonRoot": true, "seccompProfile": {"type": "RuntimeDefault"}},
		"containers": containers,
	}}},
}

with_container(patch) := deployment([object.union(good_container, patch)])

# object.union merges RECURSIVELY, so a patch that omits a key does not remove it. Tests
# that assert a MISSING field have to replace the whole sub-object, not patch into it.
with_resources(res) := deployment([object.union(
	object.remove(good_container, {"resources"}),
	{"resources": res},
)])

pdb(spec) := {
	"kind": "PodDisruptionBudget",
	"metadata": {"name": "app-backend", "labels": {
		"app.kubernetes.io/part-of": "office",
		"app.kubernetes.io/instance": "app-platform",
	}},
	"spec": object.union({"selector": {"matchLabels": {"app.kubernetes.io/component": "backend"}}}, spec),
}

# --- disruption budgets --------------------------------------------------------------------

test_pdb_maxunavailable_passes if {
	count(deny) == 0 with input as pdb({"maxUnavailable": 1})
}

test_pdb_minavailable_denied if {
	count(deny) > 0 with input as pdb({"minAvailable": 1})
}

test_pdb_without_either_denied if {
	count(deny) > 0 with input as pdb({})
}

test_pdb_empty_selector_denied if {
	count(deny) > 0 with input as {
		"kind": "PodDisruptionBudget",
		"metadata": {"name": "app-backend"},
		"spec": {"maxUnavailable": 1, "selector": {"matchLabels": {}}},
	}
}

# --- images ---------------------------------------------------------------------------------

test_pinned_image_passes if {
	count(deny) == 0 with input as with_container({})
}

test_latest_tag_denied if {
	count(deny) > 0 with input as with_container({"image": "docker.io/nginxinc/nginx-unprivileged:latest"})
}

test_untagged_image_denied if {
	count(deny) > 0 with input as with_container({"image": "docker.io/nginxinc/nginx-unprivileged"})
}

test_unknown_registry_denied if {
	count(deny) > 0 with input as with_container({"image": "evil.example.com/nginx:1.0"})
}

# --- resources ------------------------------------------------------------------------------

test_missing_cpu_request_denied if {
	count(deny) > 0 with input as with_resources({
		"requests": {"memory": "32Mi"},
		"limits": {"memory": "128Mi"},
	})
}

test_missing_memory_limit_denied if {
	count(deny) > 0 with input as with_resources({
		"requests": {"cpu": "10m", "memory": "32Mi"},
	})
}

# The one rule that denies something most policy suites REQUIRE. A cpu limit throttles
# rather than protects; this asserts we still reject it on purpose.
test_cpu_limit_denied if {
	count(deny) > 0 with input as with_resources({
		"requests": {"cpu": "10m", "memory": "32Mi"},
		"limits": {"cpu": "500m", "memory": "128Mi"},
	})
}

# --- security context -----------------------------------------------------------------------

test_privilege_escalation_denied if {
	count(deny) > 0 with input as with_container({"securityContext": {
		"allowPrivilegeEscalation": true,
		"capabilities": {"drop": ["ALL"]},
	}})
}

test_missing_capability_drop_denied if {
	count(deny) > 0 with input as deployment([object.union(
		object.remove(good_container, {"securityContext"}),
		{"securityContext": {
			"allowPrivilegeEscalation": false,
			"capabilities": {"drop": ["NET_RAW"]},
		}},
	)])
}

test_run_as_root_denied if {
	count(deny) > 0 with input as {
		"kind": "Deployment",
		"metadata": {"name": "app-media-proxy"},
		"spec": {"template": {"spec": {
			"priorityClassName": "office-app",
			"securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
			"containers": [good_container],
		}}},
	}
}

test_missing_seccomp_denied if {
	count(deny) > 0 with input as {
		"kind": "Deployment",
		"metadata": {"name": "app-media-proxy"},
		"spec": {"template": {"spec": {
			"priorityClassName": "office-app",
			"securityContext": {"runAsNonRoot": true},
			"containers": [good_container],
		}}},
	}
}

# --- network policy -------------------------------------------------------------------------

netpol(excepts) := {
	"kind": "NetworkPolicy",
	"metadata": {"name": "app", "labels": {
		"app.kubernetes.io/part-of": "office",
		"app.kubernetes.io/instance": "app-platform",
	}},
	"spec": {"egress": [{
		"to": [{"ipBlock": {"cidr": "0.0.0.0/0", "except": excepts}}],
		"ports": [{"protocol": "TCP", "port": 443}],
	}]},
}

test_external_egress_with_all_excepts_passes if {
	count(deny) == 0 with input as netpol(["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"])
}

# The link-local range is the one most likely to be left out, and it is the one that
# reaches the cloud metadata endpoint at 169.254.169.254.
test_external_egress_without_link_local_denied if {
	count(deny) > 0 with input as netpol(["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"])
}

test_external_egress_with_no_excepts_denied if {
	count(deny) > 0 with input as netpol([])
}
