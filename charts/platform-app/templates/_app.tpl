{{- define "platform.app.name" -}}
{{- required "platform-app: .Values.app is required" .Values.app -}}
{{- end -}}

{{/* HTTPRoute name: <app> for the unnamed route, <app>-<name> otherwise. */}}
{{- define "platform.app.routeName" -}}
{{- $app := index . 0 -}}{{- $route := index . 1 -}}
{{- if $route.name }}{{ printf "%s-%s" $app $route.name }}{{ else }}{{ $app }}{{ end -}}
{{- end -}}
