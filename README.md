# FirstTry — Virtual Try-On Backend

FastAPI service that runs AI-powered virtual try-on and returns Google Cloud Storage URLs for all generated images. Designed to run on Google Cloud Run.

## Models

| Model | Use case | Multi-garment | Prompt |
|---|---|---|---|
| `virtual-try-on-001` | Single garment, highest accuracy | ✗ | ✗ |
| `gemini-3.1-flash-image` | Single or multiple garments at once | ✓ | ✓ |

Both models run through **Vertex AI** using the same GCP project, credentials, and billing account.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `POST` | `/tryon` | Run virtual try-on, upload assets to GCS, return URLs |

See [API_DOCS.md](API_DOCS.md) for full request/response reference and code examples.

## GCS output structure

```
VTON/{generation_id}/
  model.png          ← person image
  garment.png        ← primary garment
  garment_1.png      ← second garment (Gemini multi-garment only)
  garment_2.png      ← third garment  (Gemini multi-garment only)
  result_0.png       ← generated try-on result
  result_1.png       ← additional result (virtual-try-on-001, sample_count > 1)
```

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
# All tests (VTO-001 + Gemini single + Gemini multi-garment)
python test_api.py

# Single test
python test_api.py vto
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
