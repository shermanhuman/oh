---
name: telnyx-call-control
description: Syntax cheatsheet for Telnyx Voice API v2 Call Control. Covers inbound call handling, answer, playback, recording, and webhook events.
---

# Telnyx Call Control — Syntax Cheatsheet

## Auth

All requests: `Authorization: Bearer <TELNYX_API_KEY>`

Base URL: `https://api.telnyx.com`

---

## Key Endpoints

### Answer a call

```
POST /v2/calls/{call_control_id}/actions/answer
Content-Type: application/json

{
  "client_state": "aGVsbG8=",   // optional, base64
  "command_id": "unique-uuid"    // optional, idempotency
}
```

### Play audio

```
POST /v2/calls/{call_control_id}/actions/playback_start
Content-Type: application/json

{
  "audio_url": "https://example.com/greeting.mp3",
  "client_state": "aGVsbG8=",
  "command_id": "unique-uuid",
  "overlay": false,              // true to mix with call audio
  "target_legs": "self"          // "self", "opposite", "both"
}
```

### Start recording

```
POST /v2/calls/{call_control_id}/actions/record_start
Content-Type: application/json

{
  "format": "mp3",               // "mp3" or "wav"
  "channels": "single",          // "single" or "dual"
  "play_beep": true,             // beep at start
  "max_length": 300,             // max seconds (0 = infinite, max 14400)
  "timeout_secs": 5,             // silence timeout (0 = infinite)
  "trim": "trim-silence",        // remove leading/trailing silence
  "recording_track": "inbound",  // "both", "inbound", "outbound"
  "client_state": "aGVsbG8=",
  "command_id": "unique-uuid"
}
```

### Hang up

```
POST /v2/calls/{call_control_id}/actions/hangup
Content-Type: application/json

{
  "client_state": "aGVsbG8=",
  "command_id": "unique-uuid"
}
```

### List recordings

```
GET /v2/recordings
GET /v2/recordings/{recording_id}
DELETE /v2/recordings/{recording_id}
```

---

## Webhook Events

All webhooks are POST JSON to your configured webhook URL.

### Common envelope

```json
{
  "event_type": "call.initiated",
  "payload": {
    "call_control_id": "v3:xxx",
    "call_leg_id": "uuid",
    "call_session_id": "uuid",
    "connection_id": "1234567890",
    "from": "+12125551234",
    "to": "+18005551234",
    "direction": "incoming",
    "client_state": null,
    "occurred_at": "2026-01-15T10:30:00.000Z",
    "state": "ringing"
  },
  "record_type": "event"
}
```

### Event types for voicemail flow

| Event                  | Trigger                | Next action           |
| ---------------------- | ---------------------- | --------------------- |
| `call.initiated`       | Inbound call arrives   | `answer`              |
| `call.answered`        | Call answered          | `playback_start`      |
| `call.playback.ended`  | Audio finished playing | `record_start`        |
| `call.recording.saved` | Recording complete     | Download + transcribe |
| `call.hangup`          | Call ended             | Log, cleanup          |
| `call.recording.error` | Recording failed       | Log error             |

### `call.recording.saved` payload

```json
{
  "event_type": "call.recording.saved",
  "payload": {
    "call_control_id": "v3:xxx",
    "call_leg_id": "uuid",
    "call_session_id": "uuid",
    "connection_id": "1234567890",
    "recording_urls": {
      "mp3": "https://api.telnyx.com/v2/recordings/xxx/mp3",
      "wav": "https://api.telnyx.com/v2/recordings/xxx/wav"
    },
    "channels": "single",
    "duration_millis": 15000,
    "from": "+12125551234",
    "to": "+18005551234",
    "public_recording_urls": {
      "mp3": "https://telnyx-recording.s3.amazonaws.com/xxx.mp3",
      "wav": "https://telnyx-recording.s3.amazonaws.com/xxx.wav"
    }
  }
}
```

---

## Go HTTP Client Pattern

```go
func (c *TelnyxClient) Answer(ctx context.Context, callControlID string) error {
    url := fmt.Sprintf("https://api.telnyx.com/v2/calls/%s/actions/answer", callControlID)
    req, _ := http.NewRequestWithContext(ctx, "POST", url, strings.NewReader(`{}`))
    req.Header.Set("Authorization", "Bearer "+c.apiKey)
    req.Header.Set("Content-Type", "application/json")
    resp, err := c.httpClient.Do(req)
    if err != nil {
        return fmt.Errorf("telnyx answer: %w", err)
    }
    defer resp.Body.Close()
    if resp.StatusCode != http.StatusOK {
        body, _ := io.ReadAll(resp.Body)
        return fmt.Errorf("telnyx answer: status %d: %s", resp.StatusCode, body)
    }
    return nil
}
```

---

## Webhook Signature Verification

Telnyx sends two headers for Ed25519 verification:

- `telnyx-signature-ed25519` — base64-encoded signature
- `telnyx-timestamp` — Unix timestamp string

Verify: decode signature, construct `timestamp|payload` message, verify with Telnyx public key.

Public key endpoint: `GET https://api.telnyx.com/v2/public_key`

---

## Gotchas

- `call_control_id` is URL-encoded in paths (contains colons in v3 format)
- `client_state` must be base64-encoded
- `connection_id` = Voice API Application ID (set in Mission Control)
- Recording URLs in `call.recording.saved` are temporary — download promptly
- `timeout_secs` on `record_start` uses internal transcription for silence detection (charges apply)
- `playback_start` requires a publicly accessible URL for the audio file
