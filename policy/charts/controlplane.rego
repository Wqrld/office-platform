# The control plane's objects survive their own release. Every object the control-plane
# chart renders lives in flux-system and carries `helm.sh/resource-policy: keep`: a
# failed first install is an uninstall (helm-controller's remediation), an uninstall
# deletes what Helm created, and a deleted Kustomization with prune on garbage-collects
# every namespace it had adopted. That is how production was lost once, on
# 2026-09-16 (fixed in 2.0.0, CHANGELOG.md). The annotation is what makes it impossible; this is what keeps it there.
#
# Except the per-app Kustomizations: Helm honours `keep` on upgrades too, so with it an
# app switched off would stay running. Their data lives in the platform layer.
package main

import rego.v1

deny contains msg if {
	input.metadata.namespace == "flux-system"
	not startswith(input.metadata.name, "app-")
	not object.get(input.metadata, ["annotations", "helm.sh/resource-policy"], "") == "keep"
	msg := sprintf(
		"%s/%s is a control-plane object without helm.sh/resource-policy: keep — a failed install would uninstall it, and a pruning Kustomization takes its inventory with it",
		[input.kind, input.metadata.name],
	)
}

deny contains msg if {
	input.kind == "Kustomization"
	startswith(input.metadata.name, "app-")
	object.get(input.metadata, ["annotations", "helm.sh/resource-policy"], "") == "keep"
	msg := sprintf("Kustomization/%s carries helm.sh/resource-policy: keep — switching the app off would leave it running", [input.metadata.name])
}
