{{- define "tenants.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: {{ .Values.tenant }}
app.kubernetes.io/name: {{ .Release.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* One password from the generator, under the key named. Call with (list $ "key"). */}}
{{- define "tenants.draw" -}}
- sourceRef: {generatorRef: {apiVersion: generators.external-secrets.io/v1alpha1, kind: ClusterGenerator, name: {{ (index . 0).Values.passwordGenerator }}}}
  rewrite: [{regexp: {source: password, target: {{ index . 1 }}}}]
{{- end -}}
