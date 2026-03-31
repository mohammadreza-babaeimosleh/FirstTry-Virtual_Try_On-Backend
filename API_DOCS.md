# Virtual Try-On API — Documentation

Base URL: `https://vton-api-234062011057.us-central1.run.app`

---

## Endpoints

### `GET /health`
Returns `200 OK` when the service is running.

### `POST /tryon`
Runs virtual try-on and returns GCS URLs for all generated images.

#### Request body (JSON)

| Field | Type | Required | Description |
|---|---|---|---|
| `model_image_url` | string | ✅ | Public URL of the person / model photo |
| `garment_image_url` | string | ✅ | Public URL of the garment / product photo |
| `sample_count` | int | ❌ | Number of results to generate (1–4, default `1`) |
| `output_format` | string | ❌ | `"png"` (default) or `"jpeg"` |

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

---

## Python

### Using `requests`

```python
import requests

BASE_URL = "https://vton-api-234062011057.us-central1.run.app"

response = requests.post(
    f"{BASE_URL}/tryon",
    json={
        "model_image_url":   "https://example.com/person.jpg",
        "garment_image_url": "https://example.com/shirt.jpg",
        "sample_count":      1,
        "output_format":     "png",
    },
    timeout=300,
)
response.raise_for_status()
data = response.json()

print("Generation ID:", data["generation_id"])
print("Result URL:   ", data["result_urls"][0])
```

### Download the result image

```python
import requests
from pathlib import Path

result_url = data["result_urls"][0]
img_bytes = requests.get(result_url, timeout=30).content
Path("result.png").write_bytes(img_bytes)
print("Saved to result.png")
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

### Using `fetch` (browser or Node.js 18+)

```javascript
const BASE_URL = "https://vton-api-234062011057.us-central1.run.app";

async function runTryOn(modelImageUrl, garmentImageUrl) {
  const response = await fetch(`${BASE_URL}/tryon`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model_image_url:   modelImageUrl,
      garment_image_url: garmentImageUrl,
      sample_count:      1,
      output_format:     "png",
    }),
    signal: AbortSignal.timeout(300_000),   // 5-minute timeout
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`HTTP ${response.status}: ${err}`);
  }

  const data = await response.json();
  console.log("Generation ID:", data.generation_id);
  console.log("Result URL:   ", data.result_urls[0]);
  return data;
}

// Usage
runTryOn(
  "https://example.com/person.jpg",
  "https://example.com/shirt.jpg"
).catch(console.error);
```

### Using `axios` (Node.js / browser)

```javascript
import axios from "axios";

const BASE_URL = "https://vton-api-234062011057.us-central1.run.app";

async function runTryOn(modelImageUrl, garmentImageUrl) {
  const { data } = await axios.post(
    `${BASE_URL}/tryon`,
    {
      model_image_url:   modelImageUrl,
      garment_image_url: garmentImageUrl,
      sample_count:      1,
      output_format:     "png",
    },
    { timeout: 300_000 }
  );

  console.log("Result URL:", data.result_urls[0]);
  return data;
}
```

### TypeScript types

```typescript
interface TryOnRequest {
  model_image_url:   string;
  garment_image_url: string;
  sample_count?:     number;   // 1–4, default 1
  output_format?:    "png" | "jpeg";
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
curl -X POST https://vton-api-234062011057.us-central1.run.app/tryon \
  -H "Content-Type: application/json" \
  -d '{
    "model_image_url":   "https://example.com/person.jpg",
    "garment_image_url": "https://example.com/shirt.jpg",
    "sample_count":      1,
    "output_format":     "png"
  }'
```

---

## PHP

```php
<?php

$baseUrl = "https://vton-api-234062011057.us-central1.run.app";

$payload = json_encode([
    "model_image_url"   => "https://example.com/person.jpg",
    "garment_image_url" => "https://example.com/shirt.jpg",
    "sample_count"      => 1,
    "output_format"     => "png",
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

struct TryOnRequest: Encodable {
    let model_image_url:   String
    let garment_image_url: String
    let sample_count:      Int
    let output_format:     String
}

struct TryOnResponse: Decodable {
    let generation_id: String
    let folder:        String
    let model_url:     String
    let garment_url:   String
    let result_urls:   [String]
}

func runTryOn(modelURL: String, garmentURL: String) async throws -> TryOnResponse {
    let url = URL(string: "https://vton-api-234062011057.us-central1.run.app/tryon")!
    var request = URLRequest(url: url, timeoutInterval: 300)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = try JSONEncoder().encode(TryOnRequest(
        model_image_url:   modelURL,
        garment_image_url: garmentURL,
        sample_count:      1,
        output_format:     "png"
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
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class TryOnResult(
    val generationId: String,
    val resultUrls:   List<String>,
    val modelUrl:     String,
    val garmentUrl:   String,
)

suspend fun runTryOn(modelImageUrl: String, garmentImageUrl: String): TryOnResult =
    withContext(Dispatchers.IO) {
        val url  = URL("https://vton-api-234062011057.us-central1.run.app/tryon")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod    = "POST"
            doOutput         = true
            connectTimeout   = 10_000
            readTimeout      = 300_000
            setRequestProperty("Content-Type", "application/json")
        }

        val body = JSONObject().apply {
            put("model_image_url",   modelImageUrl)
            put("garment_image_url", garmentImageUrl)
            put("sample_count",      1)
            put("output_format",     "png")
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
| `422` | Validation error | Invalid `sample_count`, missing URL, unreachable image URL |
| `500` | Server error | Vertex AI failure, GCS write error |

Vertex AI inference typically takes **10–30 seconds**. Set your HTTP client timeout to at least **300 seconds**.
