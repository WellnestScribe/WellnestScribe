# Azure: switch the note-generation model / update the key (for Gary)

Plain-English steps to (a) change which GPT model WellNest uses to write notes, and
(b) rotate the Azure key if it's ever exposed. No code changes — it's all
environment variables.

## The four settings that control note generation

| Setting | What it is | Current value |
|---|---|---|
| `SCRIBE_AZURE_OPENAI_ENDPOINT` | The Azure resource URL | `https://garybryan2021-0878-foun-resource.cognitiveservices.azure.com/` |
| `SCRIBE_AZURE_OPENAI_KEY` | The API key for that resource | (secret — in the portal) |
| `SCRIBE_AZURE_OPENAI_DEPLOYMENT` | **Which model** — the deployment name | `gpt-5-mini` |
| `SCRIBE_AZURE_OPENAI_API_VERSION` | Azure API version | `2025-04-01-preview` |
| `SCRIBE_REASONING_EFFORT` | How hard the model "thinks" (`minimal`/`low`/`medium`) | `low` |

The full `gpt-5-chat` model stays configured separately under `AZURE_OPENAI_*`; we
do not delete it.

## Where to change these

There are **two** places, and they are independent:

- **Local (your laptop / dev):** the `.env` file in the project root.
- **Production (the live website):** **Azure App Service → your web app →
  Settings → Configuration → Application settings.** The live site does **NOT**
  read `.env` — it only reads App Service settings. Changing `.env` does nothing to
  production.

## A. Switch the note model (e.g. gpt-5-mini ⇄ gpt-5-chat)

1. Decide the deployment name you want: `gpt-5-mini` (cheaper) or `gpt-5-chat`
   (full quality). It must match a **deployment** that exists in the Azure OpenAI
   resource (Azure AI Foundry → Deployments).
2. **Local:** open `.env`, set `SCRIBE_AZURE_OPENAI_DEPLOYMENT=gpt-5-mini`, save.
3. **Production:** Azure Portal → App Service → Configuration → Application
   settings → find `SCRIBE_AZURE_OPENAI_DEPLOYMENT` (or **+ New application
   setting** if missing) → set value to `gpt-5-mini` → **Save**.
4. **Restart** so the change takes effect:
   - Local: stop `python manage.py runserver` (Ctrl+C) and start it again.
   - Production: App Service → **Restart** (or it restarts automatically on Save).

To revert to the full model, set the value back to `gpt-5-chat` and restart.

## B. Update / rotate the key (do this if a key was ever shared or leaked)

1. Azure Portal → open the Azure OpenAI resource
   (`garybryan2021-0878-foun-resource`).
2. Left menu → **Keys and Endpoint**.
3. Click **Regenerate Key 1** (or Key 2). This **immediately invalidates the old
   key**, so do the next step right away to avoid downtime.
4. **Copy** the new key.
5. Update it everywhere it's used:
   - **Local `.env`:** `SCRIBE_AZURE_OPENAI_KEY=<new key>` (and `AZURE_OPENAI_KEY=`
     / `AZURE_OPENAI_AGENT_KEY=` if they point at the same resource — they
     currently do).
   - **Production App Service** Application settings: same key names → new value.
6. **Restart** local and production (as in A.4).

## C. Adjust how hard the model thinks (fabrication vs cost)

`gpt-5-mini` invents less when it reasons more, but that costs a little more.

- `SCRIBE_REASONING_EFFORT=minimal` — cheapest/fastest, most likely to fabricate.
- `SCRIBE_REASONING_EFFORT=low` — current; cross-checks the transcript. Recommended
  for Patois.
- `medium` — even safer, a bit more cost.

Change it the same way (`.env` locally, App Service in production) and restart.

## D. Confirm it worked

After restart, generate a note. In the app logs you'll see a line like:

```
chat call: model=gpt-5-mini finish=stop reasoning_tokens=... completion_tokens=...
```

- `model=` confirms the deployment in use.
- `reasoning_tokens=` > 0 confirms reasoning is on (0 means `minimal`).

Azure's own **Metrics** blade shows token/call counts within a few minutes;
**Cost Management** dollars lag 8–24 h.
