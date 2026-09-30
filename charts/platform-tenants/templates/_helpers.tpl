{{- define "tenants.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: {{ .Values.tenant }}
app.kubernetes.io/name: {{ .Release.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- /*
One realm client, from an app's `oidc` entry. Call with (list $app $oidc $domain).
Every shape is a confidential client with no implicit flow, no password grant — a browser
application with a second, weaker way in that nothing needs — and no service account.
*/ -}}
{{- define "tenants.client" -}}
{{- $app := index . 0 }}{{ $o := index . 1 }}{{ $url := printf "https://%s.%s" $app (index . 2) -}}
{{- $shape := $o.shape | default "lasuite" -}}
clientId: {{ $app }}
name: {{ $o.name | default (title $app) }}
description: {{ $o.description | quote }}
enabled: true
protocol: openid-connect
publicClient: false
clientAuthenticatorType: client-secret
secret: $(env:CLIENT_SECRET_{{ upper $app }})
implicitFlowEnabled: false
directAccessGrantsEnabled: false
serviceAccountsEnabled: false
{{- if eq $shape "resource-server" }}
alwaysDisplayInConsole: false
standardFlowEnabled: false
{{- else if has $shape (list "lasuite" "login") }}
alwaysDisplayInConsole: true
standardFlowEnabled: true
rootUrl: {{ $url }}
baseUrl: {{ $url }}
adminUrl: {{ $url }}
redirectUris: [{{ $url }}{{ $o.redirect | default "/*" }}]
webOrigins: [{{ $url }}]
frontchannelLogout: {{ eq $shape "lasuite" }}
attributes:
  {{- if eq $shape "lasuite" }}
  backchannel.logout.url: {{ $url }}/api/v1.0/logout/
  backchannel.logout.session.required: "true"
  frontchannel.logout.url: {{ $url }}/api/v1.0/logout/
  frontchannel.logout.session.required: "false"
  {{- end }}
  post.logout.redirect.uris: {{ $url }}/*
  {{- with $o.accessTokenLifespan }}
  access.token.lifespan: {{ . | quote }}
  {{- end }}
{{- else }}
{{- fail (printf "apps.%s.oidc.shape must be lasuite, login or resource-server" $app) }}
{{- end }}
{{- with $o.audiences }}
protocolMappers:
  {{- range . }}
  - name: {{ . }}-audience
    protocol: openid-connect
    protocolMapper: oidc-audience-mapper
    config:
      included.client.audience: {{ . }}
      access.token.claim: "true"
      id.token.claim: "false"
  {{- end }}
{{- end }}
{{- end -}}

{{/* One password from the generator, under the key named. Call with (list $ "key"). */}}
{{- define "tenants.draw" -}}
- sourceRef: {generatorRef: {apiVersion: generators.external-secrets.io/v1alpha1, kind: ClusterGenerator, name: {{ (index . 0).Values.passwordGenerator }}}}
  rewrite: [{regexp: {source: password, target: {{ index . 1 }}}}]
{{- end -}}

{{/* OpenSearch roles: `indices_all` on exactly the app's patterns. Call with the users map. */}}
{{- define "tenants.opensearchRoles" -}}
_meta: {type: roles, config_version: 2}
{{- range $app, $patterns := . }}
{{ $app }}_service:
  reserved: false
  cluster_permissions: [cluster_composite_ops]
  index_permissions:
    - index_patterns: {{ toJson $patterns }}
      allowed_actions: [indices_all]
{{- end }}
{{ end -}}

{{- define "tenants.opensearchMapping" -}}
_meta: {type: rolesmapping, config_version: 2}
{{- range $app, $_ := . }}
{{ $app }}_service:
  reserved: false
  users: [{{ $app }}]
{{- end }}
{{ end -}}
