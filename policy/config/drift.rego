# The datastores put back a hand edit (adr/0119): the broker once sat at 0/0 replicas after
# its HelmRelease was resumed, and every Flux object said Ready. Keyed on the release names,
# because conftest sees files, not paths.
package main

import rego.v1

drift_corrected := {"valkey-cache", "valkey-broker", "opensearch"}

deny contains msg if {
	input.kind == "HelmRelease"
	input.metadata.namespace == "office-data"
	input.metadata.name in drift_corrected
	not input.spec.driftDetection.mode == "enabled"
	msg := sprintf(
		"HelmRelease/%s does not set driftDetection.mode: enabled — a hand-scaled datastore stays scaled (adr/0119)",
		[input.metadata.name],
	)
}
