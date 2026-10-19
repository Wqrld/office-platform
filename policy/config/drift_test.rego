# Both directions for drift.rego.
package main

import rego.v1

datastore(name, spec) := {
	"apiVersion": "helm.toolkit.fluxcd.io/v2",
	"kind": "HelmRelease",
	"metadata": {"name": name, "namespace": "office-data"},
	"spec": object.union({"chart": {"spec": {"chart": "valkey", "version": "0.12.0"}}}, spec),
}

test_broker_with_drift_detection_passes if {
	count(deny) == 0 with input as datastore("valkey-broker", {"driftDetection": {"mode": "enabled"}})
}

test_broker_without_drift_detection_denied if {
	count(deny) > 0 with input as datastore("valkey-broker", {})
}

test_broker_with_warn_only_denied if {
	count(deny) > 0 with input as datastore("valkey-broker", {"driftDetection": {"mode": "warn"}})
}

test_other_release_needs_nothing if {
	count(deny) == 0 with input as datastore("tenants", {})
}
