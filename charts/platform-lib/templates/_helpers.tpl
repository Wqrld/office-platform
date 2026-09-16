{{/*
Names, labels and selectors.

The unit here is a COMPONENT, not an application (adr/0002). Nine of fifteen apps have
more than one workload and Docs has five, so every helper takes the root context, a
component name, and that component's values. An application is a map of components.

`platform.name` is the application; `platform.componentName` is one workload within it.
Both are prefixed with the tenant, because the release name and the namespace are the
only two handles that reach a resource an upstream chart generates (adr/0008). Neither
reaches inside DINUM's templates, so anything a chart hardcodes without the release
name stays a per-app finding.
*/}}

{{- define "platform.name" -}}
{{- .Values.nameOverride | default .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* One workload within the app. Call with (list $ "backend"). */}}
{{- define "platform.componentName" -}}
{{- $root := index . 0 -}}
{{- $component := index . 1 -}}
{{- printf "%s-%s" (include "platform.name" $root) $component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Labels carried by everything we create.

`app.kubernetes.io/instance` is the one that matters operationally: it is what the
surround's selectors match against, and what ties an object we made to the release that
made it. `part-of` is the tenant so a whole platform is selectable in one query.
*/}}
{{- define "platform.labels" -}}
{{- $root := index . 0 -}}
helm.sh/chart: {{ printf "%s-%s" $root.Chart.Name $root.Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/managed-by: {{ $root.Release.Service }}
app.kubernetes.io/part-of: {{ $root.Values.tenant | default "office" }}
{{ include "platform.selector" . }}
{{- end -}}

{{/*
The selector half — the subset that must stay stable across upgrades, so it never
carries the chart version. Call with (list $) or (list $ "backend").
*/}}
{{- define "platform.selector" -}}
{{- $root := index . 0 -}}
app.kubernetes.io/name: {{ include "platform.name" $root }}
app.kubernetes.io/instance: {{ $root.Release.Name }}
{{- if gt (len .) 1 }}
{{- $component := index . 1 }}
{{- if $component }}
app.kubernetes.io/component: {{ $component }}
{{- end }}
{{- end }}
{{- end -}}

{{/*
The namespace an app's objects land in. Stated rather than inferred so a chart that
creates something cross-namespace has one place to ask.
*/}}
{{- define "platform.namespace" -}}
{{- .Release.Namespace -}}
{{- end -}}
