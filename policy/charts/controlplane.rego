# The control plane's objects survive their own release. Every object the control-plane
# chart renders lives in flux-system and carries `helm.sh/resource-policy: keep`: a
# failed first install is an uninstall (helm-controller's remediation), an uninstall
# deletes what Helm created, and a deleted Kustomization with prune on garbage-collects
# every namespace it had adopted. That is how production was lost once (PROGRESS.md,
# 2026-09-16). The annotation is what makes it impossible; this is what keeps it there.
package main

import rego.v1

deny contains msg if {
	input.metadata.namespace == "flux-system"
	object.get(input.metadata, ["annotations", "helm.sh/resource-policy"], "") != "keep"
	msg := sprintf(
		"%s/%s is a control-plane object without helm.sh/resource-policy: keep — a failed install would uninstall it, and a pruning Kustomization takes its inventory with it",
		[input.kind, input.metadata.name],
	)
}
