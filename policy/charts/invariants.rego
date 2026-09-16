# The platform's own hard invariants, asserted against rendered output.
#
# These are the rules 10-verification.md lists for Kyverno. Kyverno is not installed
# (adr/0102 — PSA first), so until it is, this is where they live: the same assertions,
# checked at render time instead of at admission. When Kyverno arrives these become its
# fixtures rather than being deleted.
package main

import rego.v1

# --- disruption budgets -----------------------------------------------------------------
# The invariant 10-verification.md names as "the one most likely to regress silently".
# A minAvailable PDB on a single-replica workload blocks every drain, and nothing fails
# until someone drains a node — by which time it reads as a node problem, not a chart one.

deny contains msg if {
	input.kind == "PodDisruptionBudget"
	input.spec.minAvailable
	msg := sprintf(
		"PodDisruptionBudget/%s uses minAvailable — always maxUnavailable: on a single replica minAvailable blocks every drain",
		[input.metadata.name],
	)
}

deny contains msg if {
	input.kind == "PodDisruptionBudget"
	not input.spec.maxUnavailable
	msg := sprintf("PodDisruptionBudget/%s sets neither maxUnavailable nor minAvailable", [input.metadata.name])
}

deny contains msg if {
	input.kind == "PodDisruptionBudget"
	count(object.get(input, ["spec", "selector", "matchLabels"], {})) == 0
	msg := sprintf("PodDisruptionBudget/%s has an empty selector — it would match every pod in the namespace", [input.metadata.name])
}

# --- images -----------------------------------------------------------------------------
# Pinned, and from a registry we have decided on. A floating tag makes a redeploy a
# different deployment.

allowed_registries := {"docker.io/", "ghcr.io/", "harbor.mijnbureau.haaijer.dev/", "quay.io/", "registry.k8s.io/"}

containers contains c if {
	input.kind == "Deployment"
	some c in input.spec.template.spec.containers
}

containers contains c if {
	input.kind == "Deployment"
	some c in object.get(input, ["spec", "template", "spec", "initContainers"], [])
}

deny contains msg if {
	some c in containers
	endswith(c.image, ":latest")
	msg := sprintf("container %q runs %s — :latest makes a redeploy a different deployment", [c.name, c.image])
}

deny contains msg if {
	some c in containers
	not contains(c.image, ":")
	msg := sprintf("container %q runs %s with no tag at all", [c.name, c.image])
}

deny contains msg if {
	some c in containers
	not startswith_any(c.image, allowed_registries)
	msg := sprintf("container %q runs %s — not from an allowed registry", [c.name, c.image])
}

startswith_any(s, prefixes) if {
	some p in prefixes
	startswith(s, p)
}

# --- resources --------------------------------------------------------------------------
# Requests for both, a memory limit, and deliberately NO cpu limit: a cpu limit throttles
# rather than protects, and on a single node the scheduler needs the request, not the cap.

deny contains msg if {
	some c in containers
	not object.get(c, ["resources", "requests", "cpu"], false)
	msg := sprintf("container %q has no cpu request — the scheduler cannot place it honestly", [c.name])
}

deny contains msg if {
	some c in containers
	not object.get(c, ["resources", "requests", "memory"], false)
	msg := sprintf("container %q has no memory request", [c.name])
}

deny contains msg if {
	some c in containers
	not object.get(c, ["resources", "limits", "memory"], false)
	msg := sprintf("container %q has no memory limit — one leak takes the node down", [c.name])
}

deny contains msg if {
	some c in containers
	object.get(c, ["resources", "limits", "cpu"], false)
	msg := sprintf("container %q sets a cpu limit — deliberately not done here: it throttles rather than protects", [c.name])
}

# --- security context -------------------------------------------------------------------
# PSA `restricted`, asserted at render time (adr/0102). Collabora needs four capabilities
# back, but Collabora is an upstream chart — nothing platform-app renders is exempt.

deny contains msg if {
	input.kind == "Deployment"
	not input.spec.template.spec.securityContext.runAsNonRoot
	msg := sprintf("Deployment/%s does not set runAsNonRoot", [input.metadata.name])
}

deny contains msg if {
	input.kind == "Deployment"
	input.spec.template.spec.securityContext.seccompProfile.type != "RuntimeDefault"
	msg := sprintf("Deployment/%s does not set seccompProfile RuntimeDefault", [input.metadata.name])
}

deny contains msg if {
	some c in containers
	c.securityContext.allowPrivilegeEscalation != false
	msg := sprintf("container %q does not set allowPrivilegeEscalation: false", [c.name])
}

deny contains msg if {
	some c in containers
	not "ALL" in object.get(c, ["securityContext", "capabilities", "drop"], [])
	msg := sprintf("container %q does not drop ALL capabilities", [c.name])
}

# --- network policy ---------------------------------------------------------------------
# An `external: true` egress rule must not open the cluster's own address space. The
# link-local range matters as much as RFC1918: 169.254.169.254 is the cloud metadata
# endpoint, and an app that can reach it can often read instance credentials.

required_excepts := {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"}

deny contains msg if {
	input.kind == "NetworkPolicy"
	some rule in object.get(input, ["spec", "egress"], [])
	some to in object.get(rule, ["to"], [])
	to.ipBlock.cidr == "0.0.0.0/0"
	some needed in required_excepts
	not needed in object.get(to, ["ipBlock", "except"], [])
	msg := sprintf(
		"NetworkPolicy/%s allows 0.0.0.0/0 without excepting %s",
		[input.metadata.name, needed],
	)
}
