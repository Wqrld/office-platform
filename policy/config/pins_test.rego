# Both directions for every rule in pins.rego.
#
# A policy suite that has only ever run against compliant input is indistinguishable from
# an empty one. These assert that each rule actually bites.
#
#   conftest verify --policy policy
package main

import rego.v1

release(spec) := {
	"apiVersion": "helm.toolkit.fluxcd.io/v2",
	"kind": "HelmRelease",
	"metadata": {"name": "docs", "namespace": "office-docs"},
	"spec": spec,
}

# --- semver ranges ---------------------------------------------------------------------------

test_exact_chart_version_passes if {
	count(deny) == 0 with input as release({"chart": {"spec": {"chart": "collabora-online", "version": "1.3.2"}}})
}

test_caret_range_denied if {
	count(deny) > 0 with input as release({"chart": {"spec": {"chart": "collabora-online", "version": "^1.3.2"}}})
}

test_tilde_range_denied if {
	count(deny) > 0 with input as release({"chart": {"spec": {"chart": "collabora-online", "version": "~1.3"}}})
}

test_wildcard_range_denied if {
	count(deny) > 0 with input as release({"chart": {"spec": {"chart": "collabora-online", "version": "1.3.x"}}})
}

test_gte_range_denied if {
	count(deny) > 0 with input as release({"chart": {"spec": {"chart": "collabora-online", "version": ">=1.3.2"}}})
}

# --- sources ---------------------------------------------------------------------------------

test_gitrepository_with_tag_passes if {
	count(deny) == 0 with input as {
		"apiVersion": "source.toolkit.fluxcd.io/v1",
		"kind": "GitRepository",
		"metadata": {"name": "suitenumerique-docs"},
		"spec": {"url": "https://github.com/suitenumerique/docs", "ref": {"tag": "v5.5.0"}},
	}
}

test_gitrepository_on_a_branch_denied if {
	count(deny) > 0 with input as {
		"apiVersion": "source.toolkit.fluxcd.io/v1",
		"kind": "GitRepository",
		"metadata": {"name": "suitenumerique-docs"},
		"spec": {"url": "https://github.com/suitenumerique/docs", "ref": {"branch": "main"}},
	}
}

test_ocirepository_with_tag_passes if {
	count(deny) == 0 with input as {
		"apiVersion": "source.toolkit.fluxcd.io/v1",
		"kind": "OCIRepository",
		"metadata": {"name": "platform-app"},
		"spec": {"url": "oci://harbor/office/charts/platform-app", "ref": {"tag": "0.2.4"}},
	}
}

test_ocirepository_unpinned_denied if {
	count(deny) > 0 with input as {
		"apiVersion": "source.toolkit.fluxcd.io/v1",
		"kind": "OCIRepository",
		"metadata": {"name": "platform-app"},
		"spec": {"url": "oci://harbor/office/charts/platform-app", "ref": {}},
	}
}

test_ocirepository_semver_denied if {
	count(deny) > 0 with input as {
		"apiVersion": "source.toolkit.fluxcd.io/v1",
		"kind": "OCIRepository",
		"metadata": {"name": "platform-app"},
		"spec": {"url": "oci://harbor/office/charts/platform-app", "ref": {"semver": ">=0.2.0"}},
	}
}

# --- image tags ------------------------------------------------------------------------------

test_pinned_image_tag_passes if {
	count(deny) == 0 with input as release({
		"chart": {"spec": {"chart": "src/helm/impress", "version": "5.5.0"}},
		"values": {"backend": {"image": {"tag": "v5.5.0"}}},
	})
}

test_latest_image_tag_denied if {
	count(deny) > 0 with input as release({
		"chart": {"spec": {"chart": "src/helm/impress", "version": "5.5.0"}},
		"values": {"backend": {"image": {"tag": "latest"}}},
	})
}

# --- migration remediation -------------------------------------------------------------------

test_migration_with_retries_zero_passes if {
	count(deny) == 0 with input as release({
		"chart": {"spec": {"chart": "src/helm/impress", "version": "5.5.0"}},
		"upgrade": {"remediation": {"retries": 0}},
		"values": {"backend": {"migrate": {"enabled": true}}},
	})
}

# The failure mode: Helm rolls the CODE back and leaves the SCHEMA where the half-applied
# migration left it, then tries again.
test_migration_without_remediation_denied if {
	count(deny) > 0 with input as release({
		"chart": {"spec": {"chart": "src/helm/impress", "version": "5.5.0"}},
		"values": {"backend": {"migrate": {"enabled": true}}},
	})
}

test_migration_with_retries_nonzero_denied if {
	count(deny) > 0 with input as release({
		"chart": {"spec": {"chart": "src/helm/impress", "version": "5.5.0"}},
		"upgrade": {"remediation": {"retries": 3}},
		"values": {"backend": {"migrate": {"enabled": true}}},
	})
}

# A release with no migration is not required to set it.
test_no_migration_no_remediation_passes if {
	count(deny) == 0 with input as release({
		"chart": {"spec": {"chart": "collabora-online", "version": "1.3.2"}},
		"values": {"image": {"tag": "26.04.3.2.1"}},
	})
}
