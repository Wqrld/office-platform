# Static rules on the config repo: decisions already made, encoded so they survive the
# person who made them (10-verification.md, "Static rules on the config repo").
#
# These run over the SOURCE files, not the rendered output, because that is where a pin
# lives. Everything here is a few lines of rego standing in for a paragraph in an ADR.
package main

import rego.v1

# --- no semver ranges ---------------------------------------------------------------------
# adr/0003. One bad upstream release must not be able to reach prod everywhere at once. A
# range is anything that is not a bare version: "^1.2", "~1.2", ">=1.2", "1.2.x", "*".

range_markers := ["^", "~", ">", "<", "*", " - ", "x", "X"]

is_range(v) if {
	some m in range_markers
	contains(v, m)
}

deny contains msg if {
	input.kind == "HelmRelease"
	v := input.spec.chart.spec.version
	is_range(v)
	msg := sprintf(
		"HelmRelease/%s pins chart version %q — a semver range lets an upstream release reach the cluster with nothing changed here (adr/0003)",
		[input.metadata.name, v],
	)
}

deny contains msg if {
	input.kind in {"OCIRepository", "GitRepository", "HelmChart"}
	v := input.spec.ref.semver
	msg := sprintf(
		"%s/%s uses ref.semver %q — pin an exact tag instead (adr/0003)",
		[input.kind, input.metadata.name, v],
	)
}

# A source that pins nothing at all follows the default branch, which is worse than a range.
deny contains msg if {
	input.kind == "GitRepository"
	not input.spec.ref.tag
	not input.spec.ref.commit
	msg := sprintf(
		"GitRepository/%s pins neither a tag nor a commit — it follows a moving branch",
		[input.metadata.name],
	)
}

deny contains msg if {
	input.kind == "OCIRepository"
	not input.spec.ref.tag
	not input.spec.ref.digest
	msg := sprintf("OCIRepository/%s pins neither a tag nor a digest", [input.metadata.name])
}

# --- images pinned separately from the chart ------------------------------------------------
# adr/0012. A chart bump must not be able to move the application underneath it, so the image
# tag is stated in our values even when the chart would default it correctly.

deny contains msg if {
	input.kind == "HelmRelease"
	walk(input.spec.values, [path, node])
	path[count(path) - 1] == "tag"
	is_string(node)
	node == "latest"
	msg := sprintf(
		"HelmRelease/%s sets an image tag of \"latest\" at %v — a redeploy would be a different deployment",
		[input.metadata.name, path],
	)
}

# --- migrations must not be retried ---------------------------------------------------------
# Decided in 04-platform-charts.md. A failed migration retried automatically compounds the
# failure: Helm rolls back the code and leaves the schema where the migration left it.
# Only asserted for releases that actually run one, which here is any release whose values
# mention a migrate job.

runs_migration if {
	walk(input.spec.values, [path, _])
	some seg in path
	is_string(seg)
	contains(lower(seg), "migrate")
}

deny contains msg if {
	input.kind == "HelmRelease"
	runs_migration
	not input.spec.upgrade.remediation.retries == 0
	msg := sprintf(
		"HelmRelease/%s runs a migration Job but does not set upgrade.remediation.retries: 0 — a retried migration compounds a failure instead of stopping at it",
		[input.metadata.name],
	)
}
