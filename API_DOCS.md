# Virtual Try-On API — Documentation

Base URL: `https://vton-api-234062011057.us-central1.run.app`

---

## Endpoints

### `GET /health`
Returns `200 OK` when the service is running.

### `POST /tryon`
Runs virtual try-on and returns GCS URLs for all generated images.

#### Request body (JSON)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `model_image_url` | string | ✅ | — | Public URL of the person / model photo |
| `garment_image_urls` | string **or** string[] | ✅¹ | — | Single garment URL (string) **or** list of garment URLs. Multiple URLs require `gemini-3.1-flash-image`. Takes priority over `garment_image_url` |
| `garment_image_url` | string | ✅¹ | — | **Legacy.** Single garment URL. Use `garment_image_urls` for new integrations |
| `model` | string | ❌ | `"virtual-try-on-001"` | AI model to use. See [Models](#models) below |
| `sample_count` | int | ❌ | `1` | Number of results to generate (1–4). Applies to `virtual-try-on-001` only |
| `output_format` | string | ❌ | `"png"` | `"png"` or `"jpeg"` |

> ¹ One of `garment_image_urls` or `garment_image_url` is required. If both are sent, `garment_image_urls` wins.

#### Response body (JSON)

```json
{
  "generation_id": "0ecc17ffbcb84d9980a883dac920e9aa",
  "folder": "VTON/0ecc17ffbcb84d9980a883dac920e9aa",
  "model_url": "https://storage.googleapis.com/firsttry-results/VTON/.../model.png",
  "garment_url": "https://storage.googleapis.com/firsttry-results/VTON/.../garment.png",
  "result_urls": [
    "https://storage.googleapis.com/firsttry-results/VTON/.../result_0.png"
  ]
}
```

> `garment_url` always points to the primary garment (`garment_image_url`). Additional garments are saved to the same GCS folder as `garment_1.png`, `garment_2.png`, etc., but are not included in the response.

---

## Models

### `virtual-try-on-001` (default)

Purpose-built Vertex AI model for single-garment try-on. Highest accuracy for garment texture and body preservation.

- Single garment only — passing `garment_image_urls` returns a `422` error
- Supports `sample_count` 1–4 to generate multiple result variations
- No prompt support

### `gemini-3.1-flash-image`

Gemini image editing model via Vertex AI. Supports multiple garments dressed on the model simultaneously.

- Pass additional garments in `garment_image_urls`
- Always returns 1 result image (`sample_count` is ignored)
- Guided by a built-in VTO prompt — no custom prompt needed

---

## Examples

### Single garment — default model (virtual-try-on-001)

```json
{
  "model_image_url":    "https://example.com/person.jpg",
  "garment_image_urls": "https://example.com/shirt.jpg"
}
```

### Single garment — Gemini

```json
{
  "model_image_url":    "https://example.com/person.jpg",
  "garment_image_urls": "https://example.com/shirt.jpg",
  "model":              "gemini-3.1-flash-image"
}
```

### Multiple garments — Gemini

```json
{
  "model_image_url":    "https://example.com/person.jpg",
  "garment_image_urls": [
    "https://example.com/shirt.jpg",
    "https://example.com/pants.jpg",
    "https://example.com/jacket.jpg"
  ],
  "model": "gemini-3.1-flash-image"
}
```

---

## Python

### Using `requests`

```python
import requests

BASE_URL = "https://vton-api-234062011057.us-central1.run.app"

# Single garment (default model) — string form
response = requests.post(
    f"{BASE_URL}/tryon",
    json={
        "model_image_url":    "https://example.com/person.jpg",
        "garment_image_urls": "https://example.com/shirt.jpg",
        "sample_count":       1,
        "output_format":      "png",
    },
    timeout=300,
)
response.raise_for_status()
data = response.json()
print("Result URL:", data["result_urls"][0])

# Multi-garment (Gemini) — list form
response = requests.post(
    f"{BASE_URL}/tryon",
    json={
        "model_image_url":    "https://example.com/person.jpg",
        "garment_image_urls": [
            "https://example.com/shirt.jpg",
            "https://example.com/pants.jpg",
        ],
        "model":         "gemini-3.1-flash-image",
        "output_format": "png",
    },
    timeout=300,
)
response.raise_for_status()
data = response.json()
print("Result URL:", data["result_urls"][0])
```

### Download the result image

```python
from pathlib import Path

result_url = data["result_urls"][0]
img_bytes = requests.get(result_url, timeout=30).content
Path("result.png").write_bytes(img_bytes)
```

### Using `httpx` (async)

```python
import asyncio
import httpx

BASE_URL = "https://vton-api-234062011057.us-central1.run.app"

async def run_tryon():
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{BASE_URL}/tryon",
            json={
                "model_image_url":   "https://example.com/person.jpg",
                "garment_image_url": "https://example.com/shirt.jpg",
            },
        )
        response.raise_for_status()
        data = response.json()
        print("Result:", data["result_urls"][0])

asyncio.run(run_tryon())
```

---

## JavaScript / TypeScript

### Using `fetch`

```javascript
const BASE_URL = "https://vton-api-234062011057.us-central1.run.app";

// garmentImageUrls accepts a single string URL or an array of URLs
async function runTryOn({ modelImageUrl, garmentImageUrls, model = "virtual-try-on-001" }) {
  const response = await fetch(`${BASE_URL}/tryon`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model_image_url:    modelImageUrl,
      garment_image_urls: garmentImageUrls,
      model,
      sample_count:  1,
      output_format: "png",
    }),
    signal: AbortSignal.timeout(300_000),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`HTTP ${response.status}: ${err}`);
  }

  return response.json();
}

// Single garment — string form
runTryOn({ modelImageUrl: "https://example.com/person.jpg", garmentImageUrls: "https://example.com/shirt.jpg" });

// Multi-garment — array form
runTryOn({
  modelImageUrl:    "https://example.com/person.jpg",
  garmentImageUrls: ["https://example.com/shirt.jpg", "https://example.com/pants.jpg"],
  model:            "gemini-3.1-flash-image",
});
```

### Using `axios`

```javascript
import axios from "axios";

const BASE_URL = "https://vton-api-234062011057.us-central1.run.app";

const { data } = await axios.post(
  `${BASE_URL}/tryon`,
  {
    model_image_url:    "https://example.com/person.jpg",
    garment_image_urls: "https://example.com/shirt.jpg",
    model:              "virtual-try-on-001",
  },
  { timeout: 300_000 }
);

console.log("Result URL:", data.result_urls[0]);
```

### TypeScript types

```typescript
type TryOnModel = "virtual-try-on-001" | "gemini-3.1-flash-image";

interface TryOnRequest {
  model_image_url:    string;
  garment_image_urls: string | string[];  // single URL string or array; multiple items require gemini-3.1-flash-image
  model?:             TryOnModel;         // default: "virtual-try-on-001"
  sample_count?:      number;             // 1–4, default 1; virtual-try-on-001 only
  output_format?:     "png" | "jpeg";     // default: "png"
}

interface TryOnResponse {
  generation_id: string;
  folder:        string;
  model_url:     string;
  garment_url:   string;
  result_urls:   string[];
}
```

---

## cURL

```bash
# Single garment — default model (string form)
curl -X POST https://vton-api-234062011057.us-central1.run.app/tryon \
  -H "Content-Type: application/json" \
  -d '{
    "model_image_url":    "https://example.com/person.jpg",
    "garment_image_urls": "https://example.com/shirt.jpg",
    "sample_count":       1,
    "output_format":      "png"
  }'

# Multi-garment — Gemini (array form)
curl -X POST https://vton-api-234062011057.us-central1.run.app/tryon \
  -H "Content-Type: application/json" \
  -d '{
    "model_image_url":    "https://example.com/person.jpg",
    "garment_image_urls": ["https://example.com/shirt.jpg", "https://example.com/pants.jpg"],
    "model":              "gemini-3.1-flash-image",
    "output_format":      "png"
  }'
```

---

## PHP

```php
<?php

$baseUrl = "https://vton-api-234062011057.us-central1.run.app";

$payload = json_encode([
    "model_image_url"    => "https://example.com/person.jpg",
    "garment_image_urls" => "https://example.com/shirt.jpg",
    "model"              => "virtual-try-on-001",
    "sample_count"       => 1,
    "output_format"      => "png",
]);

$ch = curl_init("$baseUrl/tryon");
curl_setopt_array($ch, [
    CURLOPT_POST           => true,
    CURLOPT_POSTFIELDS     => $payload,
    CURLOPT_HTTPHEADER     => ["Content-Type: application/json"],
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT        => 300,
]);

$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

if ($httpCode !== 200) {
    throw new Exception("HTTP $httpCode: $response");
}

$data = json_decode($response, true);
echo "Result URL: " . $data["result_urls"][0] . PHP_EOL;
```

---

## Swift (iOS / macOS)

```swift
import Foundation

// garment_image_urls accepts a single string or an array — model Swift enum handles both
enum GarmentURLs: Encodable {
    case single(String)
    case multiple([String])

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .single(let url):   try container.encode(url)
        case .multiple(let urls): try container.encode(urls)
        }
    }
}

struct TryOnRequest: Encodable {
    let model_image_url:    String
    let garment_image_urls: GarmentURLs
    let model:              String
    let sample_count:       Int
    let output_format:      String
}

struct TryOnResponse: Decodable {
    let generation_id: String
    let folder:        String
    let model_url:     String
    let garment_url:   String
    let result_urls:   [String]
}

func runTryOn(modelURL: String, garmentURLs: [String], model: String = "virtual-try-on-001") async throws -> TryOnResponse {
    let url = URL(string: "https://vton-api-234062011057.us-central1.run.app/tryon")!
    var request = URLRequest(url: url, timeoutInterval: 300)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    let garments: GarmentURLs = garmentURLs.count == 1 ? .single(garmentURLs[0]) : .multiple(garmentURLs)
    request.httpBody = try JSONEncoder().encode(TryOnRequest(
        model_image_url:    modelURL,
        garment_image_urls: garments,
        model:              model,
        sample_count:       1,
        output_format:      "png"
    ))

    let (data, response) = try await URLSession.shared.data(for: request)
    guard (response as? HTTPURLResponse)?.statusCode == 200 else {
        throw URLError(.badServerResponse)
    }
    return try JSONDecoder().decode(TryOnResponse.self, from: data)
}
```

---

## Kotlin (Android)

```kotlin
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class TryOnResult(
    val generationId: String,
    val resultUrls:   List<String>,
    val modelUrl:     String,
    val garmentUrl:   String,
)

suspend fun runTryOn(
    modelImageUrl:    String,
    garmentImageUrls: List<String>,              // single-element list or multiple for multi-garment
    model:            String = "virtual-try-on-001",
): TryOnResult = withContext(Dispatchers.IO) {
    val url  = URL("https://vton-api-234062011057.us-central1.run.app/tryon")
    val conn = (url.openConnection() as HttpURLConnection).apply {
        requestMethod  = "POST"
        doOutput       = true
        connectTimeout = 10_000
        readTimeout    = 300_000
        setRequestProperty("Content-Type", "application/json")
    }

    // garment_image_urls: send a string for a single garment, array for multiple
    val garmentValue: Any = if (garmentImageUrls.size == 1) garmentImageUrls[0] else JSONArray(garmentImageUrls)
    val body = JSONObject().apply {
        put("model_image_url",    modelImageUrl)
        put("garment_image_urls", garmentValue)
        put("model",              model)
        put("sample_count",       1)
        put("output_format",      "png")
    }.toString()

    conn.outputStream.use { it.write(body.toByteArray()) }
    check(conn.responseCode == 200) { "HTTP ${conn.responseCode}" }

    val json = JSONObject(conn.inputStream.bufferedReader().readText())
    TryOnResult(
        generationId = json.getString("generation_id"),
        resultUrls   = json.getJSONArray("result_urls").let { arr ->
            List(arr.length()) { arr.getString(it) }
        },
        modelUrl   = json.getString("model_url"),
        garmentUrl = json.getString("garment_url"),
    )
}
```

---

## Error reference

| HTTP code | Meaning | Common cause |
|---|---|---|
| `200` | Success | — |
| `422` | Validation error | Unsupported `model` value; `garment_image_urls` sent with `virtual-try-on-001`; missing or unreachable image URL; invalid `sample_count` |
| `500` | Server error | Vertex AI / Gemini returned no images; GCS write error |

Inference typically takes **10–30 seconds**. Set your HTTP client timeout to at least **300 seconds**.
