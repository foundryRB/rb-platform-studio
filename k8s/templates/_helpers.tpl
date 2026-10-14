{{/* Common labels applied to every resource in this chart. */}}
{{- define "platform-studio.labels" -}}
app.kubernetes.io/name: platform-studio
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: platform-studio
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Subset suitable for matchLabels / selector. */}}
{{- define "platform-studio.selectorLabels" -}}
app.kubernetes.io/name: platform-studio
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
