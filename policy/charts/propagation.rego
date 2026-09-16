# Do the platform-wide values actually REACH the rendered objects?
#
# Ported from mijn-bureau's tests/{cluster,container,resource}-rules — the one part of that
# repo worth carrying over wholesale (mijn-bureau-vs-office-platform.md calls it "the single
# most transferable asset"). The failure it catches is specific and silent: a global is set,
# a template stops threading it through, every object still renders and every object is
# subtly wrong. Nothing else in CI notices, because the output is still valid YAML that the
# API server accepts.
#
# These run over tests/golden/, so they cover every case in tests/cases/index.yaml.
package main

import rego.v1

# --- tenant -----------------------------------------------------------------------------
# `tenant` is one of only two handles that reach a resource an upstream chart generates
# (adr/0008). If it stops landing in part-of, "select the whole platform in one query"
# quietly stops being true.

selectable_kinds := {
	"HTTPRoute", "BackendTrafficPolicy", "NetworkPolicy", "PodDisruptionBudget",
	"Deployment", "Service", "ServiceMonitor", "ExternalSecret",
}

deny contains msg if {
	selectable_kinds[input.kind]
	not input.metadata.labels["app.kubernetes.io/part-of"]
	msg := sprintf(
		"%s/%s has no app.kubernetes.io/part-of — the tenant did not propagate",
		[input.kind, input.metadata.name],
	)
}

deny contains msg if {
	selectable_kinds[input.kind]
	not input.metadata.labels["app.kubernetes.io/instance"]
	msg := sprintf(
		"%s/%s has no app.kubernetes.io/instance — the surround's selectors match on it",
		[input.kind, input.metadata.name],
	)
}

# --- gateway ----------------------------------------------------------------------------
# Every route must attach to the shared Gateway, by name AND namespace AND listener. A
# parentRef missing its sectionName attaches to every listener including :80, which is a
# route reachable over plaintext that nobody asked for.

deny contains msg if {
	input.kind == "HTTPRoute"
	count(object.get(input, ["spec", "parentRefs"], [])) == 0
	msg := sprintf("HTTPRoute/%s has no parentRefs — it attaches to nothing", [input.metadata.name])
}

deny contains msg if {
	input.kind == "HTTPRoute"
	some ref in input.spec.parentRefs
	not ref.sectionName
	msg := sprintf(
		"HTTPRoute/%s parentRef %q has no sectionName — it would attach to every listener, :80 included",
		[input.metadata.name, ref.name],
	)
}

deny contains msg if {
	input.kind == "HTTPRoute"
	some ref in input.spec.parentRefs
	not ref.namespace
	msg := sprintf(
		"HTTPRoute/%s parentRef %q has no namespace — it would resolve in the app's own namespace, where there is no Gateway",
		[input.metadata.name, ref.name],
	)
}

# --- hostnames --------------------------------------------------------------------------
# A route with no hostname matches every host on the listener.

deny contains msg if {
	input.kind == "HTTPRoute"
	count(object.get(input, ["spec", "hostnames"], [])) == 0
	msg := sprintf("HTTPRoute/%s has no hostnames — it would match every host on the listener", [input.metadata.name])
}

# --- priority class ---------------------------------------------------------------------
# The two workloads the surround runs itself must carry one. Without it they are the first
# thing evicted under pressure, which on this single node is exactly when /media matters.

deny contains msg if {
	input.kind == "Deployment"
	not input.spec.template.spec.priorityClassName
	msg := sprintf("Deployment/%s has no priorityClassName — it is first to be evicted under pressure", [input.metadata.name])
}
