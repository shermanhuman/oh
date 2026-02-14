---
name: postmark-api
description: Postmark API syntax — sending transactional emails, batch emails, and attachments. Use when integrating Postmark or sending email from application code.
---

# Postmark Email — Syntax Cheatsheet

## Auth

All requests require a server-level token:

```
X-Postmark-Server-Token: <SERVER_TOKEN>
Content-Type: application/json
Accept: application/json
```

Base URL: `https://api.postmarkapp.com`

---

## Send Single Email

```
POST /email
```

### Request body

```json
{
  "From": "Support <support@example.com>",
  "To": "recipient@example.com",
  "Subject": "Voicemail from +12125551234",
  "HtmlBody": "<h2>New Voicemail</h2><p><strong>From:</strong> +12125551234</p>",
  "TextBody": "New Voicemail\nFrom: +12125551234\nTranscript: ...",
  "Tag": "voicemail",
  "ReplyTo": "support@example.com",
  "MessageStream": "outbound",
  "TrackOpens": true,
  "TrackLinks": "None",
  "Headers": [
    {
      "Name": "X-Call-ID",
      "Value": "call-session-uuid"
    }
  ],
  "Metadata": {
    "caller": "+12125551234",
    "source": "my-app"
  }
}
```

### Response (200 OK)

```json
{
  "To": "recipient@example.com",
  "SubmittedAt": "2026-02-10T12:00:00.000-05:00",
  "MessageID": "uuid-here",
  "ErrorCode": 0,
  "Message": "OK"
}
```

---

## Body Fields Reference

| Field           | Type   | Required | Description                                                            |
| --------------- | ------ | -------- | ---------------------------------------------------------------------- |
| `From`          | string | **yes**  | Sender. Must have confirmed Sender Signature. Format: `"Name <email>"` |
| `To`            | string | **yes**  | Recipient(s). Comma-separated. Max 50.                                 |
| `Cc`            | string | no       | CC recipients. Comma-separated. Max 50.                                |
| `Bcc`           | string | no       | BCC recipients. Comma-separated. Max 50.                               |
| `Subject`       | string | no       | Email subject line                                                     |
| `HtmlBody`      | string | yes\*    | HTML body. Required if no `TextBody`.                                  |
| `TextBody`      | string | yes\*    | Plain text body. Required if no `HtmlBody`.                            |
| `Tag`           | string | no       | Categorization tag. Max 1000 chars.                                    |
| `ReplyTo`       | string | no       | Reply-To address. Comma-separated.                                     |
| `Headers`       | array  | no       | Custom headers: `[{"Name": "X-Foo", "Value": "bar"}]`                  |
| `TrackOpens`    | bool   | no       | Track email opens                                                      |
| `TrackLinks`    | string | no       | `None`, `HtmlAndText`, `HtmlOnly`, `TextOnly`                          |
| `Metadata`      | object | no       | Key-value pairs for filtering/analytics                                |
| `Attachments`   | array  | no       | File attachments (base64 encoded)                                      |
| `MessageStream` | string | no       | Stream ID. Default: `"outbound"`                                       |

---

## Attachments Format

```json
{
  "Attachments": [
    {
      "Name": "recording.mp3",
      "Content": "base64-encoded-content-here",
      "ContentType": "audio/mpeg"
    }
  ]
}
```

---

## Batch Send

```
POST /email/batch
```

Body is a JSON array of email objects (same format as single). Max 500 messages, 50MB total.

---

## Error Codes

| Code | Meaning               |
| ---- | --------------------- |
| 0    | OK                    |
| 300  | Invalid email request |
| 406  | Inactive recipient    |
| 422  | Invalid JSON          |

---

## curl Example

```bash
curl "https://api.postmarkapp.com/email" \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Postmark-Server-Token: $POSTMARK_SERVER_TOKEN" \
  -d '{
    "From": "support@example.com",
    "To": "recipient@example.com",
    "Subject": "Voicemail from +12125551234",
    "TextBody": "New voicemail transcript...",
    "Tag": "voicemail",
    "MessageStream": "outbound"
  }'
```

---

## Go Client Pattern

```go
type PostmarkEmail struct {
    From          string            `json:"From"`
    To            string            `json:"To"`
    Subject       string            `json:"Subject"`
    HtmlBody      string            `json:"HtmlBody,omitempty"`
    TextBody      string            `json:"TextBody,omitempty"`
    Tag           string            `json:"Tag,omitempty"`
    ReplyTo       string            `json:"ReplyTo,omitempty"`
    MessageStream string            `json:"MessageStream,omitempty"`
    Metadata      map[string]string `json:"Metadata,omitempty"`
    Headers       []struct {
        Name  string `json:"Name"`
        Value string `json:"Value"`
    } `json:"Headers,omitempty"`
}

func (c *PostmarkClient) Send(ctx context.Context, email PostmarkEmail) error {
    body, err := json.Marshal(email)
    if err != nil {
        return fmt.Errorf("postmark marshal: %w", err)
    }

    req, _ := http.NewRequestWithContext(ctx, "POST",
        "https://api.postmarkapp.com/email", bytes.NewReader(body))
    req.Header.Set("Accept", "application/json")
    req.Header.Set("Content-Type", "application/json")
    req.Header.Set("X-Postmark-Server-Token", c.serverToken)

    resp, err := c.httpClient.Do(req)
    if err != nil {
        return fmt.Errorf("postmark send: %w", err)
    }
    defer resp.Body.Close()

    var result struct {
        ErrorCode int    `json:"ErrorCode"`
        Message   string `json:"Message"`
        MessageID string `json:"MessageID"`
    }
    if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
        return fmt.Errorf("postmark decode: %w", err)
    }
    if result.ErrorCode != 0 {
        return fmt.Errorf("postmark error %d: %s", result.ErrorCode, result.Message)
    }
    return nil
}
```

---

## Gotchas

- `From` address must have a **confirmed Sender Signature** in Postmark
- Attachment `Content` must be **base64-encoded**
- Individual email max payload: ~10MB (including attachments)
- `MessageStream` defaults to `"outbound"` — use this for transactional emails
- Error checking: batch endpoint returns 200 even if individual messages fail — check each `ErrorCode`
- Rate limit: 10,000 emails/month on free tier; check plan for higher volumes
