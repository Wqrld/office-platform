{{/* The application table, charts/control-plane/apps.yaml. */}}
{{- define "platform.apps" -}}
{{ .Files.Get "apps.yaml" }}
{{- end }}

{{/*
The apps this cluster runs, sorted by name: every app switched on, plus every
internal app something switched on requires. Refuses a selection whose dependencies are
off, by name, so the failure is a message on the HelmRelease and not a Job that retries
against a Service that does not exist.
*/}}
{{- define "platform.enabledApps" -}}
{{- $table := include "platform.apps" . | fromYaml }}
{{- $on := list }}
{{- range $name, $app := $table }}
  {{- if and (not $app.internal) (index $.Values.apps $name) }}{{ $on = append $on $name }}{{ end }}
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
