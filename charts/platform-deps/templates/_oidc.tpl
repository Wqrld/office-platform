{{/*
The OIDC env block.

This helper exists because of ONE thing that is easy to get wrong and expensive to debug:
browser-facing endpoints must be the EXTERNAL host and server-to-server endpoints must be
the INTERNAL Service. A browser cannot reach a cluster Service; a pod should not egress to
the public name to talk to a neighbour. Keycloak accepts both because
`KC_HOSTNAME_BACKCHANNEL_DYNAMIC` is on.

Get it backwards and login works in the browser and fails at token exchange — a symptom
that reads exactly like a wrong client secret. Emitting both from one input makes that
correct by construction for every app instead of a thing each new app rediscovers.

Call with (list $ .Values.oidc) — returns the Secret's `data:` map as YAML.
The client secret is emitted as an ESO template placeholder, never as a value.
*/}}
{{- define "platform.oidc.env" -}}
{{- $root := index . 0 -}}
{{- $o := index . 1 -}}
{{- $base := required "oidc: baseDomain is required" $root.Values.baseDomain -}}
{{- $client := $o.client | default $root.Values.app -}}
{{- $realm := $o.realm | default "office" -}}
{{- $host := $o.host | default (printf "%s.%s" $root.Values.app $base) -}}
{{- $external := printf "https://%s/realms/%s/protocol/openid-connect" (printf "%s.%s" ($o.idHost | default "id") $base) $realm -}}
{{- $internal := printf "%s/realms/%s/protocol/openid-connect" $o.internalUrl $realm -}}
OIDC_RP_CLIENT_ID: {{ $client | quote }}
OIDC_RP_CLIENT_SECRET: "{{ `{{ .secret }}` }}"
OIDC_RP_SIGN_ALGO: {{ $o.signAlgo | quote }}
OIDC_RP_SCOPES: {{ $o.scopes | join " " | quote }}
{{- /* Browser-facing: the browser is redirected here, so it must be publicly reachable. */}}
OIDC_OP_AUTHORIZATION_ENDPOINT: {{ printf "%s/auth" $external | quote }}
OIDC_OP_LOGOUT_ENDPOINT: {{ printf "%s/logout" $external | quote }}
{{- /* Server-to-server: the pod calls these, so they stay inside the cluster. */}}
OIDC_OP_TOKEN_ENDPOINT: {{ printf "%s/token" $internal | quote }}
OIDC_OP_USER_ENDPOINT: {{ printf "%s/userinfo" $internal | quote }}
OIDC_OP_JWKS_ENDPOINT: {{ printf "%s/certs" $internal | quote }}
OIDC_REDIRECT_ALLOWED_HOSTS: {{ printf "https://%s" $host | quote }}
OIDC_REDIRECT_REQUIRE_HTTPS: {{ $o.requireHttps | quote }}
OIDC_USE_NONCE: {{ $o.useNonce | quote }}
OIDC_CREATE_USER: {{ $o.createUser | quote }}
OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION: {{ $o.fallbackToEmail | quote }}
OIDC_ALLOW_DUPLICATE_EMAILS: {{ $o.allowDuplicateEmails | quote }}
OIDC_STORE_ACCESS_TOKEN: {{ $o.storeAccessToken | quote }}
OIDC_STORE_ID_TOKEN: {{ $o.storeIdToken | quote }}
{{- /* Storing the refresh token needs a Fernet key in a specific format. Off until an app
       actually does token exchange, because a half-configured one fails at logout. */}}
OIDC_STORE_REFRESH_TOKEN: {{ $o.storeRefreshToken | quote }}
OIDC_USERINFO_FULLNAME_FIELDS: {{ $o.fullnameFields | join "," | quote }}
OIDC_USERINFO_SHORTNAME_FIELD: {{ $o.shortnameField | quote }}
{{- range $k, $v := $o.extraEnv }}
{{ $k }}: {{ $v | quote }}
{{- end }}
{{- end -}}
