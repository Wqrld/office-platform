{{/*
One nginx workload: its ConfigMap, Deployment and Service. The Deployment hashes the
RENDERED config, so a template fix in a chart bump restarts it like a values change does.
  root, name, conf (string), confName, w (replicas, image, priorityClassName, resources),
  volumes / mounts (extra, optional)
*/}}
{{- define "platform.nginx" -}}
{{- $selector := dict "app.kubernetes.io/name" .name }}
{{- $labels := mustMerge (deepCopy $selector) (include "platform.labels" .root | fromYaml) }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .confName }}
  namespace: {{ .root.Release.Namespace }}
  labels:
    {{- toYaml $labels | nindent 4 }}
  annotations:
    # nginx config is full of $variables; Flux's substitution would blank every one.
    kustomize.toolkit.fluxcd.io/substitute: disabled
data:
  default.conf: |
{{ .conf | indent 4 }}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .name }}
  namespace: {{ .root.Release.Namespace }}
  labels:
    {{- toYaml $labels | nindent 4 }}
spec:
  replicas: {{ .w.replicas }}
  selector:
    matchLabels:
      {{- toYaml $selector | nindent 6 }}
  template:
    metadata:
      annotations:
        checksum/config: {{ .conf | sha256sum }}
      labels:
        {{- toYaml $selector | nindent 8 }}
    spec:
      priorityClassName: {{ .w.priorityClassName }}
      securityContext:
        runAsNonRoot: true
        seccompProfile: {type: RuntimeDefault}
      containers:
        - name: nginx
          # The unprivileged image listens on 8080 as uid 101 — no root, no capabilities.
          image: {{ .w.image }}
          ports:
            - {name: http, containerPort: 8080}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
          resources:
            {{- toYaml .w.resources | nindent 12 }}
          readinessProbe:
            httpGet: {path: /healthz, port: 8080}
            initialDelaySeconds: 3
          volumeMounts:
            - {name: conf, mountPath: /etc/nginx/conf.d}
            {{- with .mounts }}{{ toYaml . | nindent 12 }}{{ end }}
            - {name: cache, mountPath: /var/cache/nginx}
            - {name: run, mountPath: /var/run}
            - {name: tmp, mountPath: /tmp}
      volumes:
        - name: conf
          configMap: {name: {{ .confName }}}
        {{- with .volumes }}{{ toYaml . | nindent 8 }}{{ end }}
        - {name: cache, emptyDir: {}}
        - {name: run, emptyDir: {}}
        - {name: tmp, emptyDir: {}}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ .name }}
  namespace: {{ .root.Release.Namespace }}
  labels:
    {{- toYaml $labels | nindent 4 }}
spec:
  selector:
    {{- toYaml $selector | nindent 4 }}
  ports:
    - {name: http, port: 8080, targetPort: 8080}
{{- end }}
