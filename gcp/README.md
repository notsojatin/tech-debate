# Cloud Run mode

This mode runs the three debate models on Google Cloud Run GPUs instead of on your machine. Kokoro (voices) and SearXNG (search) still run locally in Docker.

```
laptop                                                Cloud Run (asia-southeast1)
┌──────────────────────────┐ authproxy (ID tokens of  ┌───────────────────────────────┐
│ app ── :11441 ── proxy ──┼────────────────────────► │ tech-debate-gpt-oss-20b  (L4) │
│     ── :11442 ── proxy ──┼────────────────────────► │ tech-debate-qwen3-14b    (L4) │
│     ── :11443 ── proxy ──┼────────────────────────► │ tech-debate-gemma3-12b   (L4) │
│ kokoro, searxng (Docker) │  tech-debate-invoker)    └──────────────┬────────────────┘
└──────────────────────────┘                                         │ Cloud Storage FUSE (read-only),
                                                                     ▼ Direct VPC + Private Google Access
                                                      gs://<project>-tech-debate-models/ollama
```

- **One private service per model.** Each one runs the stock `ollama/ollama` image, pinned by digest, on a single NVIDIA L4 (24 GB). Anything up to about 20B parameters at 4-bit fits.
- **Weights in Cloud Storage, not in images.** Google recommends container images only for models under 10 GB. So the Ollama model store lives once in a bucket and is mounted read-only into every service. Changing a model means re-syncing the bucket; nothing gets rebuilt.
- **Private by default.** The services reject calls that don't carry Google credentials. `make cloud-proxy` runs `gcp/authproxy.py`, which opens a local tunnel per role and signs each request as the `tech-debate-invoker` service account. Your `gcloud` login is only used to act as that account, so the app needs no keys, and tokens are never written to disk or printed.

The models come from `config/debate.cloud.yaml`, which overlays `config/debate.yaml`:

| Role | Model | Size tier |
|---|---|---|
| Pro | `gpt-oss:20b` | 8 CPU / 32 GiB + L4 |
| Con | `qwen3:14b` | 8 CPU / 32 GiB + L4 |
| Judge | `gemma3:12b` | 8 CPU / 32 GiB + L4 |

Models of 8B or smaller get the minimum Cloud Run allows with an L4: 4 CPU / 16 GiB.

## Measured

These numbers are from one debate ("Kubernetes is overkill for most startups") in asia-southeast1, starting with every service scaled to zero:

| Step | Time |
|---|---|
| GPU instance cold start (until Ollama answers) | ~20–30 s per service |
| Model load from Cloud Storage | ~1.5–2.5 min: qwen3:14b 99 s, gemma3:12b 131 s, gpt-oss:20b 155 s |
| Warm-up of all three, in parallel | ~3 min, set by the slowest model |
| Debate phases (research, turns, judge) | ~3.7 min; each phase takes 8–24 s on the L4s |
| Audio render (local Kokoro) | ~1.6 min |
| **Total `make debate`** | **~9 min** |

The larger models also follow the turn rules better than the 4B ones: one retry in 8 turns, and every rebuttal quote matched.

## Scaling and the 10-minute grace period

Each service is set to `--min-instances 0 --max-instances 1`. When there are no requests, nothing runs and nothing is billed for compute.

- **Shutdown:** Cloud Run decides when an idle instance stops. For GPU services, it keeps an idle instance for **at most 10 minutes** after its last request, then scales to zero. No flag sets this; it's Cloud Run's own GPU behaviour.
- **No reloads:** Ollama's keep-alive is set to keep the model loaded for the instance's whole life (`OLLAMA_KEEP_ALIVE=-1`, plus `keep_alive: -1` from the app). A warm instance never reloads.
- **Billing:** GPU services require instance-based billing. While an instance is up, you pay per second for its GPU, CPU and memory, including those last idle minutes. There are no per-request fees.
- **Cost of one debate:** the debate's runtime plus up to 10 idle minutes, for each of the three services. Use the [Cloud Run pricing page](https://cloud.google.com/run/pricing) for asia-southeast1 and add a budget alert on the project. About 30 GB in a Standard bucket costs well under $1 a month.
- **Quota:** new projects get 3 L4 GPUs per region automatically, with zonal redundancy off. That's one per service at max-instances 1. A 4th service needs a quota increase.

## Steps

```bash
make cloud-setup          # once: APIs, bucket, service accounts, Private Google Access
make cloud-sync-models    # pull the models into the bucket (Cloud Build, ~10–20 min the first time)
make cloud-deploy         # create/update the three services
make cloud-status         # check settings, that the services are private, and instance counts
```

To run a debate, open two terminals:

```bash
make cloud-proxy                         # terminal 1: keep this running
```

```bash
make up MODE=cloud                       # terminal 2: local Kokoro + SearXNG
make debate MODE=cloud TOPIC="Kubernetes is overkill for most startups"
```

At the start of a debate, the app loads all three models in parallel, so the cold starts overlap instead of stacking up. `state.json` → `timings_s` shows how long each phase took.

To stop paying for storage as well:

```bash
make cloud-down           # delete the services (asks first)
```

`gcp/teardown.sh --all` also deletes the bucket and the two service accounts.

## What `cloud-setup` changes in the project

All of it is idempotent and printed as it runs:
- **APIs enabled:** Cloud Run, Cloud Build, Cloud Storage, Compute, IAM and Monitoring.
- **Bucket:** `gs://<project>-tech-debate-models` in the region, with uniform access and public access prevention.
- **Service accounts and permissions:**
  - `tech-debate-ollama` runs the services and has read-only access to the bucket only.
  - `tech-debate-build` runs the model sync. It has write access to the bucket only, plus permission to write logs.
  - `tech-debate-invoker` is what the tunnels call the services as. It has `roles/run.invoker` on the three services only, granted by `deploy.sh`. Your account gets Token Creator on this one service account, so it can act as it. To set that up for a different user, run with `PROXY_USER=someone@example.com`.
- **Network:** Private Google Access is turned on for the `default` subnet in the region, so the services can read Cloud Storage over Google's network. Teardown leaves it on.

Settings live in `gcp/config.env`, and every one can be overridden from the environment, for example `REGION=europe-west4 make cloud-deploy`. Changing models works like this:
1. Edit `config/debate.cloud.yaml`.
2. Run `make cloud-sync-models`, then `make cloud-deploy`.
3. Optionally, `WRITE_MODEL_LOCK=1 gcp/sync-models.sh` records the new digests in `models.lock`.

## Why a custom proxy

Two simpler options failed in this project:
- **Your user login:** Cloud Run rejected plain identity tokens from your `gcloud` login, with "The access token could not be verified". That happened both through the `gcloud` proxy and on a direct `curl`, and `gcloud auth login` didn't help.
- **`gcloud run services proxy` with impersonation:** its helper binary can't use impersonated credentials ("idtoken: unsupported credentials type").

`authproxy.py` gets each token from `gcloud auth print-identity-token --impersonate-service-account … --audiences <service URL>` and refreshes it every 45 minutes. It prints one line per request with the status and how long it took, which also shows each cold start.

## Read-only model store

Ollama 0.40 writes two things on top of a plain pull, and on a read-only mount it fails with `read-only file system`:
- **`manifests-v2/`:** these entries are symlinks into `blobs/`, and `gcloud storage rsync` skips symlinks.
- **`metadata/`:** created the first time a model is shown.

The sync build therefore runs `ollama show` on every model and swaps each symlink for a copy of the small manifest file it points to, before uploading. If you ever add models by hand, do the same.

## Troubleshooting

**`could not mint an ID token` when starting the proxy**
- **Cause:** your account can't act as `tech-debate-invoker`.
- **Fix:** re-run `make cloud-setup`. Fresh IAM grants can take a few minutes to apply.

**HTTP 401/403 from a service**
- **Cause:** the invoker account is missing `roles/run.invoker` on that service.
- **Fix:** re-run `make cloud-deploy`, which re-applies the grant.
- **Where to look:** Cloud Run logs the reason for each rejected request (`gcloud logging read …`).

**HTTP 500 `read-only file system`**
- **Cause:** the bucket is missing files Ollama expects (see "Read-only model store" above).
- **Fix:** re-run `make cloud-sync-models`.
