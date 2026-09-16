# Vendored CRD schemas

JSON schemas for the kinds the datreeio CRDs-catalog does not carry, so `kubeconform`
validates them instead of skipping them. Generated from the CRDs installed on the cluster:

    kubectl get crd garagebuckets.garage.rajsingh.info -o json    # and garagekeys,
                                                                 # garageclusters, garagereferencegrants

`x-kubernetes-*` extensions are stripped; nothing else is altered. Only the version this repo
actually emits is kept, and the filename carries it — GarageCluster is `v1beta2`, the other
three `v1beta1`. kubeconform looks a schema up by the object's own apiVersion, so a file
under the wrong version is not a wrong answer, it is silently no answer at all.

Regenerate them when garage-operator is bumped. A stale schema validates the old shape and
passes, which is worse than skipping it, because it looks like coverage.

Everything else — Flux's own kinds, CNPG, Keycloak, ExternalSecret, the Gateway API —
comes from the catalog at run time.
