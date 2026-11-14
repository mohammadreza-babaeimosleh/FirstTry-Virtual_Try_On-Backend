# FirstTry — Virtual Try-On Backend

FastAPI service that runs AI-powered virtual try-on and returns Google Cloud Storage URLs for all generated images. Designed to run on Google Cloud Run.

## Models

| Model | Use case | Multi-garment | Prompt |
|---|---|---|---|
| `virtual-try-on-001` | Highest accuracy for garment texture & body preservation | ✓ (combined into one photo — see below) | ✗ |
| `gemini-3.1-flash-image` | Single or multiple garments at once | ✓ (native — each its own reference image) | ✓ |

Both models run through **Vertex AI** using the same GCP project, credentials, and billing account.

**Multiple garments, two different mechanisms:** `gemini-3.1-flash-image` takes
each garment natively as its own separate reference image. `virtual-try-on-001`'s
underlying `recontext_image` API accepts exactly one product image, so when a
request supplies more than one `garment_image_url`, this backend composites
them into a single left-to-right photo (`app/imaging.py:combine_images_horizontal`)
before calling it — the same approach the FLUX and FASHN backends use for their
own single-garment-only APIs. A single garment passes through unchanged. Up to
6 garment images are accepted for `virtual-try-on-001` (a photo-legibility
cap, not a provider limit) — beyond that, `422`. `gemini-3.1-flash-image` has
no such cap in this codebase. `garment_type` is still ignored for
`virtual-try-on-001` regardless of garment count — `recontext_image` has no
prompt/text channel at all.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `POST` | `/tryon` | Run virtual try-on, upload assets to GCS, return URLs |

See [API_DOCS.md](API_DOCS.md) for full request/response reference and code examples.

## GCS output structure

```
VTON/{model}/{timestamp}_{generation_id}/
  model.png          ← person image
  garment.png        ← primary garment — for virtual-try-on-001 with more than
                        one garment, this is the composited left-to-right photo
                        actually sent to Vertex, not just the first original
  garment_1.png      ← second garment (gemini-3.1-flash-image multi-garment only —
  garment_2.png      ← third garment    virtual-try-on-001 doesn't store these
                        separately once composited into garment.png above)
  result_0.png       ← generated try-on result
  result_1.png       ← additional result (virtual-try-on-001, sample_count > 1)
```

## Results backup + auto-cleanup (optional)

By default every file above is stored permanently in `GCS_BUCKET_NAME`. Set
all six of the following to instead treat the primary bucket as
**temporary**: every file is also written to a second bucket, and the
primary copy is deleted a fixed number of minutes after upload.

```
GCS_BACKUP_BUCKET_NAME=beforeai-results-backup
RESULTS_PRIMARY_TTL_MINUTES=15
CLOUD_TASKS_PROJECT=your-gcp-project
CLOUD_TASKS_LOCATION=us-central1
CLOUD_TASKS_CLEANUP_QUEUE=results-cleanup-queue
CLOUD_TASKS_SERVICE_ACCOUNT_EMAIL=your-service-account@your-project.iam.gserviceaccount.com
CLOUD_TASKS_WORKER_URL=https://<this-service's-cloud-run-url>/internal/cleanup-object
```

- The backup copy's path strips the leading `VTON/` — e.g.
  `VTON/{model}/2026-.../result_0.png` in the primary bucket becomes
  `{model}/2026-.../result_0.png` in the backup bucket. Everything else
  about the path is unchanged.
- The backup bucket's copy is **never** deleted by this backend — it's
  meant to be permanent.
- The primary bucket's copy is deleted via a **Cloud Task scheduled at
  upload time**, set to fire exactly `RESULTS_PRIMARY_TTL_MINUTES` later
  — not a GCS bucket lifecycle rule (GCS lifecycle rules can't do
  sub-day deletion; minimum granularity is whole days).
- **Fails safe, not open:** leave any one of the six settings unset and
  every upload behaves exactly as before this feature existed — one
  bucket, permanent storage, nothing scheduled.
- One-time setup (create the backup bucket, the shared Cloud Tasks
  queue, and grant IAM) is documented once at the project level rather
  than per-backend.

## Local development

```bash
cp .env.example .env
# fill in GCP_PROJECT_ID, GCS_BUCKET_NAME, GCS_CREDENTIALS_JSON

pip install -r requirements.txt
python -m app.main
# → http://localhost:8080
```

## Run tests

```bash
# All tests (VTO-001 single + multi, Gemini single + multi)
python test_api.py

# Single test
python test_api.py vto
python test_api.py vto_multi
python test_api.py gemini
python test_api.py gemini_multi
```

## Docker

```bash
docker build -t vton-backend .
docker run --env-file .env -p 8080:8080 vton-backend
```

## Deploy to Cloud Run

```bash
gcloud run deploy vton-api \
  --source . \
  --region us-central1 \
  --service-account <SA_EMAIL> \
  --set-env-vars GCP_PROJECT_ID=<PROJECT>,GCS_BUCKET_NAME=<BUCKET>
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `GCP_PROJECT_ID` | ✅ | GCP project for Vertex AI |
| `GCS_BUCKET_NAME` | ✅ | GCS bucket for result storage |
| `GCP_LOCATION` | ❌ | Vertex AI region (default `us-central1`) |
| `GCS_CREDENTIALS_JSON` | ❌ | Service account JSON. Leave blank on Cloud Run (uses ADC) |
| `GCS_PUBLIC_BUCKET` | ❌ | `true` for permanent public URLs, `false` for signed URLs (default) |
| `WORKER_THREADS` | ❌ | Thread pool size for blocking AI calls (default `8`) |
