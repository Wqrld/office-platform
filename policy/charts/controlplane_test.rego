package main

import rego.v1

# The other rules in this package fire on these fixtures too (labels), so count only ours.
keep_denials(obj) := {m | some m in deny with input as obj; contains(m, "helm.sh/resource-policy")}

kept := {"kind": "Kustomization", "metadata": {"name": "infra", "namespace": "flux-system", "annotations": {"helm.sh/resource-policy": "keep"}}}

test_control_plane_object_with_keep_passes if {
	count(keep_denials(kept)) == 0
}

test_control_plane_object_without_keep_fails if {
	count(keep_denials({"kind": "Kustomization", "metadata": {"name": "infra", "namespace": "flux-system"}})) == 1
}

test_app_kustomization_without_keep_passes if {
	count(keep_denials({"kind": "Kustomization", "metadata": {"name": "app-docs", "namespace": "flux-system"}})) == 0
}

test_app_kustomization_with_keep_fails if {
	count(keep_denials({"kind": "Kustomization", "metadata": {"name": "app-docs", "namespace": "flux-system", "annotations": {"helm.sh/resource-policy": "keep"}}})) == 1
}

test_app_namespace_object_is_not_judged if {
	count(keep_denials({"kind": "HTTPRoute", "metadata": {"name": "docs", "namespace": "office-docs"}})) == 0
}
