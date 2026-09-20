{{/*
Labels on everything the platform charts create. `instance` is what the surround's
selectors match; `name` equals it because one release is one app.
*/}}
{{- define "platform.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: {{ .Values.tenant | default "office" }}
app.kubernetes.io/name: {{ .Release.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* The application: names every object the charts create, so it fails loudly. */}}
{{- define "platform.app" -}}
{{- required ".Values.app is required" .Values.app -}}
{{- end -}}
