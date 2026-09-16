{{/* Shared bits. `platform.deps.app` fails loudly rather than rendering `-postgres`. */}}
{{- define "platform.deps.app" -}}
{{- required "platform-deps: .Values.app is required — it names every Secret this chart creates" .Values.app -}}
{{- end -}}
