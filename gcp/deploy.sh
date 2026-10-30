#!/usr/bin/env bash
# Deploy one private Cloud Run GPU service per cloud model. Scale-to-zero, at most one instance each.
source "$(dirname "$0")/lib.sh"

deployed=""
while read -r role model <&3; do
  svc="$(service_name "$model")"
  case " $deployed " in *" $svc "*) continue ;; esac  # two roles may share a model/service
  read -r cpu memory <<<"$(size_tier "$model")"
  log "Deploying $svc ($model for $role): 1x $GPU_TYPE, $cpu CPU, $memory"
  gc run deploy "$svc" \
    --region "$REGION" \
    --image "$OLLAMA_IMAGE" \
    --no-allow-unauthenticated \
    --service-account "$RUNTIME_SA" \
    --gpu 1 --gpu-type "$GPU_TYPE" --no-gpu-zonal-redundancy \
    --cpu "$cpu" --memory "$memory" --no-cpu-throttling --cpu-boost \
    --min-instances "$MIN_INSTANCES" --max-instances "$MAX_INSTANCES" \
    --concurrency "$CONCURRENCY" --timeout "$REQUEST_TIMEOUT" --port 8080 \
    --network "$NETWORK" --subnet "$SUBNET" --vpc-egress all-traffic \
    --clear-volumes \
    --add-volume "name=models,type=cloud-storage,bucket=$BUCKET,readonly=true,mount-options=implicit-dirs" \
    --add-volume-mount "volume=models,mount-path=/models" \
    --set-env-vars "OLLAMA_HOST=0.0.0.0:8080,OLLAMA_MODELS=/models/ollama,OLLAMA_KEEP_ALIVE=-1,OLLAMA_NOPRUNE=1,OLLAMA_NUM_PARALLEL=1,OLLAMA_NO_CLOUD=1" \
    --labels "app=tech-debate,role=$role" \
    --quiet
  gc run services add-iam-policy-binding "$svc" --region "$REGION" \
    --member "serviceAccount:$INVOKER_SA" --role roles/run.invoker --quiet >/dev/null
  echo "granted run.invoker on $svc to $INVOKER_SA"
  deployed="$deployed $svc"
done 3< <(models_by_role)

log "Done. Next: gcp/status.sh, then gcp/proxy.sh (or make cloud-proxy)"
