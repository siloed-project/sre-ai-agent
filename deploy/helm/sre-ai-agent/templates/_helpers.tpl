{{- define "sre-ai-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sre-ai-agent.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- include "sre-ai-agent.name" . }}
{{- end }}
{{- end }}

{{- define "sre-ai-agent.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "sre-ai-agent.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- required "serviceAccount.name is required when serviceAccount.create=false" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
