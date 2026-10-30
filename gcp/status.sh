#!/usr/bin/env bash
# Show each cloud model service's settings, confirm it rejects unauthenticated calls, and
# (with --instances) its instance count over the last 20 minutes from Cloud Monitoring.
source "$(dirname "$0")/lib.sh"

show_instances=0
[[ "${1:-}" == "--instances" ]] && show_instances=1

instances() {  # service -> "HH:MM active/idle" samples, newest last
  local svc="$1" now start
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  start="$(date -u -v-20M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '-20 min' +%Y-%m-%dT%H:%M:%SZ)"
  curl -s -G "https://monitoring.googleapis.com/v3/projects/$PROJECT_ID/timeSeries" \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    --data-urlencode "filter=metric.type=\"run.googleapis.com/container/instance_count\" AND resource.labels.service_name=\"$svc\"" \
    --data-urlencode "interval.startTime=$start" --data-urlencode "interval.endTime=$now" \
    --data-urlencode "aggregation.alignmentPeriod=60s" --data-urlencode "aggregation.perSeriesAligner=ALIGN_MAX" |
    python3 -c '
import json, sys
series = json.load(sys.stdin).get("timeSeries", [])
by_t = {}
for s in series:
    state = s["metric"]["labels"].get("state", "?")
    for p in s["points"]:
        t = p["interval"]["endTime"][11:16]
        by_t.setdefault(t, {})[state] = int(p["value"].get("int64Value", 0))
if not by_t:
    print("    no instances in the last 20 min (scaled to zero)")
for t in sorted(by_t)[-12:]:
    print("    " + t + "  " + "  ".join(f"{k}={v}" for k, v in sorted(by_t[t].items())))
'
}

read -r -d '' DESCRIBE_PY <<'PY' || true
import json, sys
s = json.load(sys.stdin)
t = s["spec"]["template"]
ann, c = t["metadata"]["annotations"], t["spec"]["containers"][0]
lim = c["resources"]["limits"]
vols = [f'{v["name"]}:{v.get("csi", {}).get("volumeAttributes", {}).get("bucketName", "?")}'
        for v in t["spec"].get("volumes", [])]
gpu = t["spec"].get("nodeSelector", {}).get("run.googleapis.com/accelerator", "-")
print(f'    url       {s["status"].get("url")}')
print(f'    revision  {s["status"].get("latestReadyRevisionName")}')
print(f'    image     {c["image"]}')
print(f'    gpu       {lim.get("nvidia.com/gpu", "0")} x {gpu}')
print(f'    cpu/mem   {lim.get("cpu")} / {lim.get("memory")}')
print(f'    scaling   min {ann.get("autoscaling.knative.dev/minScale", "0")}, max {ann.get("autoscaling.knative.dev/maxScale", "?")}')
print(f'    volumes   {", ".join(vols) or "-"}')
PY

while read -r role model <&3; do
  svc="$(service_name "$model")"
  log "$svc  ($role: $model)"
  if ! gc run services describe "$svc" --region "$REGION" >/dev/null 2>&1; then
    echo "    not deployed"
    continue
  fi
  gc run services describe "$svc" --region "$REGION" --format json | python3 -c "$DESCRIBE_PY"
  url="$(gc run services describe "$svc" --region "$REGION" --format 'value(status.url)')"
  code="$(curl -s -o /dev/null -w '%{http_code}' "$url/api/version")"
  echo "    no-auth   HTTP $code $([[ "$code" =~ ^40[13]$ ]] && echo '(private: OK)' || echo '(UNEXPECTED)')"
  if [[ "$show_instances" -eq 1 ]]; then
    echo "    instances (per minute, max):"
    instances "$svc"
  fi
done 3< <(models_by_role)
