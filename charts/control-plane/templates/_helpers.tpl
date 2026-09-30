{{/* The application table, charts/control-plane/apps.yaml. */}}
{{- define "platform.apps" -}}
{{ .Files.Get "apps.yaml" }}
{{- end }}

{{/*
The apps this cluster runs, sorted by name: every app switched on — by the values, or by
its `default` in the table when the values do not name it — plus every internal app
something switched on requires. Refuses a name the table does not have or an internal app
(the schema only knows the values are booleans), and a selection whose dependencies are
off, by name, so the failure is a message on the HelmRelease and not a Job that retries
against a Service that does not exist.
*/}}
{{- define "platform.enabledApps" -}}
{{- $table := include "platform.apps" . | fromYaml }}
{{- range $name, $_ := .Values.apps }}
  {{- if not (hasKey $table $name) }}{{ fail (printf "apps.%s is not an application: charts/control-plane/apps.yaml lists them" $name) }}
  {{- else if (index $table $name).internal }}{{ fail (printf "apps.%s is not chosen: it runs when something that requires it does" $name) }}{{ end }}
{{- end }}
{{- $on := list }}
{{- range $name, $app := $table }}
  {{- $want := ternary (index $.Values.apps $name) $app.default (hasKey $.Values.apps $name) }}
  {{- if and (not $app.internal) $want }}{{ $on = append $on $name }}{{ end }}
{{- end }}
{{- range $name, $app := $table }}
  {{- if has $name $on }}
    {{- range $app.requires }}
      {{- if (index $table .).internal }}{{ $on = append $on . }}
      {{- else if not (has . $on) }}{{ fail (printf "apps.%s needs apps.%s, which is off" $name .) }}{{ end }}
    {{- end }}
  {{- end }}
{{- end }}
{{- range $name, $_ := $table }}{{ if has $name $on }}- {{ $name }}
{{ end }}{{ end }}
{{- end }}

{{/*
One Flux Kustomization. Every layer is the same shape — pruned, health-gated, substituted
from cluster-vars — so the shape is written once.
  name, path, components (list), dependsOn (list of names), substitute (map), root,
  keep (default true; see platform.metadata — false for what is emitted conditionally,
  because Helm honours `keep` on upgrades too and would leave a switched-off app running)
*/}}
{{- define "platform.kustomization" -}}
{{- $r := .root.Values.reconcile }}
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: {{ .name }}
  namespace: flux-system
  {{- if ne .keep false }}
  annotations: {helm.sh/resource-policy: keep}
  {{- end }}
spec:
  interval: {{ $r.interval }}
  retryInterval: {{ $r.retryInterval }}
  timeout: {{ $r.timeout }}
  prune: true
  wait: true
  sourceRef: {kind: OCIRepository, name: office-config}
  path: {{ .path }}
  {{- with .components }}
  components: {{ toJson . }}
  {{- end }}
  {{- with .dependsOn }}
  dependsOn:
    {{- range . }}
    - {name: {{ . }}}
    {{- end }}
  {{- end }}
  postBuild:
    {{- with .substitute }}
    substitute: {{ toJson . }}
    {{- end }}
    substituteFrom: [{kind: ConfigMap, name: cluster-vars}]
{{- end }}

{{/* The registry credential, on every source that pulls from our registry. */}}
{{- define "platform.pullSecret" -}}
{{- with .Values.registry.pullSecret }}secretRef: {name: {{ . }}}{{ end }}
{{- end }}

{{/*
Every hostname this cluster serves, as a JSON list: the identity provider, the published
object store when the platform runs it, and each enabled app's hosts. Substituted whole
into the Certificate's `dnsNames` (platform/gateway/certificate.yaml) — Flux substitutes on
the YAML text, so a variable can stand in for a list, which is what lets the SAN list
follow the selection when a Kustomization cannot drop a list item.
*/}}
{{- define "platform.tlsHosts" -}}
{{- $table := include "platform.apps" . | fromYaml }}
{{- $hosts := list "id" }}
{{- if eq .Values.objectStore.mode "garage" }}{{ $hosts = append $hosts "s3" }}{{ end }}
{{- range include "platform.enabledApps" . | fromYamlArray }}{{ $hosts = concat $hosts (index $table .).hosts }}{{ end }}
{{- $fqdn := list }}
{{- range $hosts }}{{ $fqdn = append $fqdn (printf "%s.%s" . $.Values.domain) }}{{ end }}
{{- $fqdn | toJson }}
{{- end }}

{{/*
The service list every app switcher shows, as one line of JSON in the lagaufre widget's
schema — `{services: [{name, url, logo, maturity}]}`: each enabled app's `switcher` entry
from the table, by name, then the account page. Substituted into `apps/services.yaml`
(see its note on the newline) and served by every app as /custom/services.json.
Account has no logo on purpose: the widget renders a first letter, and a data: URI is the
one thing this value must not carry through YAML quoting twice.
*/}}
{{- define "platform.servicesJson" -}}
{{- $table := include "platform.apps" . | fromYaml }}
{{- $services := list }}
{{- range include "platform.enabledApps" . | fromYamlArray }}
  {{- $app := index $table . }}
  {{- with $app.switcher }}
    {{- $url := printf "https://%s.%s" (first $app.hosts) $.Values.domain }}
    {{- $services = append $services (dict "name" .name "url" $url "logo" (printf "%s%s" $url .logo) "maturity" .maturity) }}
  {{- end }}
{{- end }}
{{- $services = append $services (dict "name" "Account" "url" (printf "https://id.%s/realms/office/account" .Values.domain) "maturity" "stable") }}
{{- dict "services" $services | toJson }}
{{- end }}

{{/*
What the platform provisions per application, as one line of JSON: every app in the table,
enabled or not (a disabled app keeps its data, adr/0107), with only the fields
platform-tenants reads. Substituted whole into platform/tenants.yaml's `apps:` — a one-line
value starting with `{` is read back as a map, which is what it is here for.
*/}}
{{- define "platform.tenantsJson" -}}
{{- $out := dict }}
{{- range $name, $app := include "platform.apps" . | fromYaml }}
  {{- $_ := set $out $name (pick $app "postgres" "cache" "acl" "oidc" "search" "bucket") }}
{{- end }}
{{- $out | toJson }}
{{- end }}

{{/*
The annotations that pin a LoadBalancer Service to an address, as a JSON map substituted
whole (like TLS_HOSTS): MetalLB's, or none when the cluster's own provider allocates.
*/}}
{{- define "platform.lbAnnotations" -}}
{{- $root := index . 0 }}{{ $ip := index . 1 }}
{{- if eq $root.Values.cluster.loadBalancer.kind "metallb" }}{{ dict "metallb.universe.tf/loadBalancerIPs" $ip | toJson }}{{ else }}{}{{ end }}
{{- end }}

{{/*
The cluster services this cluster installs itself — directories under cluster/; empty
when the cluster brings its own.
*/}}
{{- define "platform.clusterServices" -}}
{{- $c := .Values.cluster }}
{{- if and $c.loadBalancer.install (ne $c.loadBalancer.kind "metallb") }}{{ fail "cluster.loadBalancer.install is on, but only kind: metallb can be installed" }}{{ end }}
{{- if and $c.loadBalancer.install (not $c.loadBalancer.pool) }}{{ fail "cluster.loadBalancer.install is on, so cluster.loadBalancer.pool needs at least one address" }}{{ end }}
{{- if $c.gateway.install }}- gateway
{{ end }}
{{- if $c.loadBalancer.install }}- metallb
{{ end }}
{{- end }}

{{/*
The platform version this control plane reconciles: the config artifact and the platform
charts are pinned to it. appVersion, NOT .Chart.Version: helm-controller installs an OCI
chart as `2.0.0+<digest>` and .Chart.Version carries that suffix into every tag, which
exists nowhere. release.sh sets both to the same number.
*/}}
{{- define "platform.version" -}}
{{ .Chart.AppVersion | default .Chart.Version }}
{{- end }}

{{/*
metadata for everything this chart renders. `helm.sh/resource-policy: keep`: if this
release is ever uninstalled — and a failed first install IS an uninstall, by
helm-controller's remediation — Helm leaves these objects standing. Without it the
Kustomizations go with the release, and a deleted Kustomization with prune on garbage-
collects its whole inventory: every namespace it had adopted. That happened once.
Not on the app Kustomizations: those must go when an app is switched off.
*/}}
{{- define "platform.metadata" -}}
metadata:
  name: {{ . }}
  namespace: flux-system
  annotations: {helm.sh/resource-policy: keep}
{{- end }}
