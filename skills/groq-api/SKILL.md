---
name: groq-api
description: Groq API syntax — Whisper transcription, audio processing, and prompt-based jargon guidance. Use when calling Groq endpoints or transcribing audio.
---

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
| `model`                     | **yes**  | `whisper-large-v3` or `whisper-large-v3-turbo` or `distil-whisper-large-v3-en` |
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
| `distil-whisper-large-v3-en` | Hugging Face | Fastest  | English-only   |

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

Translates audio into English. Same parameters as transcription minus `language`.

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

    w.WriteField("model", "whisper-large-v3")
    w.WriteField("language", "en")
    w.WriteField("response_format", "json")
    w.WriteField("prompt", "Tekmetric, JSON, API, ROsearch, R-O Search")

    part, err := w.CreateFormFile("file", filename)
    if err != nil {
        return "", fmt.Errorf("groq create form file: %w", err)
    }
    if _, err := io.Copy(part, audioData); err != nil {
        return "", fmt.Errorf("groq copy audio: %w", err)
    }
    w.Close()

    req, _ := http.NewRequestWithContext(ctx, "POST",
        "https://api.groq.com/openai/v1/audio/transcriptions", &buf)
    req.Header.Set("Authorization", "Bearer "+c.apiKey)
    req.Header.Set("Content-Type", w.FormDataContentType())

    resp, err := c.httpClient.Do(req)
    if err != nil {
        return "", fmt.Errorf("groq transcribe: %w", err)
    }
    defer resp.Body.Close()

    if resp.StatusCode != http.StatusOK {
        body, _ := io.ReadAll(resp.Body)
        return "", fmt.Errorf("groq transcribe: status %d: %s", resp.StatusCode, body)
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

- Max audio file size not explicitly documented per model; keep under 25MB
- `prompt` field is for vocabulary guidance only — it will not be prepended to transcript
- `temperature=0` is the default and recommended for transcription accuracy
- `whisper-large-v3-turbo` is faster but may miss subtle jargon — test both
- Rate limits apply per-org; check `x-ratelimit-*` response headers
- Context window is 448 tokens for Whisper models (refers to internal decoder, not input audio length)
