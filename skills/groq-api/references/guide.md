# Groq Whisper — Syntax Cheatsheet

## Auth

All requests: `Authorization: Bearer <GROQ_API_KEY>`

Base URL: `https://api.groq.com`

---

## Transcription Endpoint

```
POST /openai/v1/audio/transcriptions
Content-Type: multipart/form-data
Authorization: Bearer $GROQ_API_KEY
```

### Form fields

| Field                       | Required | Description                                                                    |
| --------------------------- | -------- | ------------------------------------------------------------------------------ |
| `model`                     | **yes**  | `whisper-large-v3` or `whisper-large-v3-turbo` |
| `file`                      | yes\*    | Audio file (flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm)                   |
| `url`                       | yes\*    | Audio URL (alternative to file upload, supports Base64URL)                     |
| `language`                  | no       | ISO-639-1 code (e.g. `en`). Improves accuracy and latency.                     |
| `prompt`                    | no       | Guide transcription style/vocabulary. Match audio language.                    |
| `response_format`           | no       | `json` (default), `text`, `verbose_json`                                       |
| `temperature`               | no       | 0-1. Default 0. Higher = more random.                                          |
| `timestamp_granularities[]` | no       | `word`, `segment`. Requires `verbose_json`.                                    |

\*Either `file` or `url` must be provided.

### Response (`json` format)

```json
{
  "text": "Your transcribed text appears here...",
  "x_groq": {
    "id": "req_unique_id"
  }
}
```

### Response (`verbose_json` format)

```json
{
  "text": "Full transcript...",
  "segments": [
    {
      "start": 0.0,
      "end": 5.2,
      "text": "Segment text..."
    }
  ],
  "x_groq": { "id": "req_unique_id" }
}
```

---

## Available Models

| Model                        | Owner        | Speed    | Accuracy       |
| ---------------------------- | ------------ | -------- | -------------- |
| `whisper-large-v3`           | OpenAI       | Standard | Best           |
| `whisper-large-v3-turbo`     | OpenAI       | Faster   | Slightly lower |

**Recommendation:** Use `whisper-large-v3` for best accuracy with domain-specific jargon.

---

## Prompt Engineering for Jargon

The `prompt` field biases the model toward specific vocabulary. Include terms the caller might say:

```
Tekmetric, JSON, API, ROsearch, R-O Search, RO Search, voicemail, integration,
webhook, Shopmonkey, Mitchell, CARFAX, parts ordering, repair order, invoice,
DMS, shop management, estimate
```

**Rules:**

- Prompt should be in the same language as the audio
- Keep under ~224 tokens
- Include proper capitalization/spelling of domain terms
- Include common abbreviations and their expansions

---

## Translation Endpoint

```
POST /openai/v1/audio/translations
Content-Type: multipart/form-data
Authorization: Bearer $GROQ_API_KEY
```

Translates audio into English. Use `whisper-large-v3`; the turbo model does not support translation. Check the endpoint schema rather than forwarding transcription-only fields.

---

## curl Example

```bash
curl https://api.groq.com/openai/v1/audio/transcriptions \
  -H "Authorization: Bearer $GROQ_API_KEY" \
  -H "Content-Type: multipart/form-data" \
  -F file="@./recording.mp3" \
  -F model="whisper-large-v3" \
  -F language="en" \
  -F prompt="Tekmetric, JSON, API, ROsearch" \
  -F response_format="json"
```

---

## Go Client Pattern

```go
func (c *GroqClient) Transcribe(ctx context.Context, audioData io.Reader, filename string) (string, error) {
    var buf bytes.Buffer
    w := multipart.NewWriter(&buf)

    for key, value := range map[string]string{"model":"whisper-large-v3", "language":"en", "response_format":"json", "prompt":"Tekmetric, JSON, API, ROsearch, R-O Search"} {
        if err := w.WriteField(key, value); err != nil { return "", fmt.Errorf("groq multipart field: %w", err) }
    }

    part, err := w.CreateFormFile("file", filename)
    if err != nil {
        return "", fmt.Errorf("groq create form file: %w", err)
    }
    if _, err := io.Copy(part, audioData); err != nil {
        return "", fmt.Errorf("groq copy audio: %w", err)
    }
    if err := w.Close(); err != nil { return "", fmt.Errorf("groq close multipart: %w", err) }

    req, err := http.NewRequestWithContext(ctx, "POST",
        "https://api.groq.com/openai/v1/audio/transcriptions", &buf)
    if err != nil { return "", fmt.Errorf("groq request: %w", err) }
    req.Header.Set("Authorization", "Bearer "+c.apiKey)
    req.Header.Set("Content-Type", w.FormDataContentType())

    resp, err := c.httpClient.Do(req)
    if err != nil {
        return "", fmt.Errorf("groq transcribe: %w", err)
    }
    defer resp.Body.Close()

    if resp.StatusCode != http.StatusOK {
        return "", fmt.Errorf("groq transcribe: HTTP status %d", resp.StatusCode)
    }

    var result struct {
        Text string `json:"text"`
    }
    if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
        return "", fmt.Errorf("groq decode: %w", err)
    }
    return result.Text, nil
}
```

---

## Gotchas

- Total file limits are tier-dependent (25 MB free / 100 MB dev); direct attachments are limited to 25 MB. Larger supported inputs require URL input or chunking. Check current account limits.
- `prompt` field is for vocabulary guidance only — it will not be prepended to transcript
- `temperature=0` is the default and recommended for transcription accuracy
- `whisper-large-v3-turbo` is faster but may miss subtle jargon — test both
- Rate limits apply per-org; check `x-ratelimit-*` response headers
- Context window is 448 tokens for Whisper models (refers to internal decoder, not input audio length)

Model support and upload limits checked September 8, 2026 against [Groq speech documentation](https://console.groq.com/docs/speech-to-text). Recheck availability before choosing a model. Use context deadlines and bounded audio input; the sample buffers multipart content in memory.
