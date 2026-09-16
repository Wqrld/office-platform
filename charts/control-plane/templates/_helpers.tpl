{{/*
The application table: every app the platform knows, what it needs running first, and the
hostnames it serves. This is the one place the dependencies between applications are
stated — the ordering comments the old flat apps/kustomization.yaml carried became these
edges, which Flux enforces with `dependsOn` and health gating — and the one place the
certificate's SAN list comes from, so an app that is off has no SAN and needs no record.

`internal: true` marks an app an organisation does not choose: it is pulled in by whatever
requires it and dropped with it. Adding an application is one entry here, one directory
under apps/, and one stanza per size profile.
*/}}
{{- define "platform.apps" -}}
collabora: {hosts: [collabora]}
# Drive's `configure-wopi` Job calls Collabora's discovery endpoint at install.
drive: {requires: [collabora], hosts: [drive]}
# No browser reaches Find, but Docs does — over the public URL, because a pod-to-pod call
# carries no X-Forwarded-Proto and Find 301s it (apps/find/README.md). Without its SAN
# the handshake fails and search silently falls back to title-only.
find: {hosts: [find]}
# Docs' search-flags Job and its reindex both assume Find exists.
docs: {requires: [find], hosts: [docs]}
# Also the host CalDAV clients connect to, so its SAN is every client's handshake.
calendars: {hosts: [calendars]}
# WebRTC media; nothing but Meet uses it. `livekit.*` is the SIGNALLING host, a WebSocket
# through the Gateway; media goes to livekit.ip directly. `turn.*` is deliberately no host
# here: it points at livekit.ip, where no HTTP-01 solver can answer, and a SAN that cannot
# be validated fails the whole certificate (adr/0105).
livekit: {internal: true, hosts: [livekit]}
# Meet's backend hands the browser LiveKit's address; transcripts are delivered as Docs
# documents (apps/docs/meet-token.yaml).
meet: {requires: [docs, livekit], hosts: [meet]}
{{- end }}

{{/*
The apps this cluster runs, as a list in table order: every app switched on, plus every
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
  name, path, components (list), dependsOn (list of names), root (the chart context)
*/}}
{{- define "platform.kustomization" -}}
{{- $r := .root.Values.reconcile }}
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata: {name: {{ .name }}, namespace: flux-system}
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
