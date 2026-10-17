# Warehouse Safety Agent

Hackathon app for team-9: an **unsafe-event queue** over VAST VSS (not a fork of `vss-blueprint`).

Clips live in the shared team index (`eskisehir_plant`, `parcel_demo`). This repo is **code only** — no videos, no `/config` secrets.

Open the deployed demo from [workshop.thecosmoslabs.com](https://workshop.thecosmoslabs.com) → **App** (`/app`).

## Split

| Person | Owns | Start here |
|---|---|---|
| A — agent / data | `api/` | Search VSS, classify, fill `/events` |
| B — UI / demo | `web/` | Unsafe queue, player, class chips; mock from `events.sample.json` until A is live |

Agree the JSON in `CONTRACT.md` before changing field names.

## Local (Person B, no VSS)

```bash
cd api && pip install -r requirements.txt
USE_SAMPLE=1 python main.py
# open http://127.0.0.1:8080
```

## Sponsors to show in the 2-minute demo

1. **VAST** — indexed clips + search
2. **NVIDIA Cosmos** (CoreWeave) — captions / detections on the playing clip
3. **Weights & Biases** — caption → class, severity, action

## Do not

- Commit `.mp4`s or team passwords
- Push to `vast-data/vast-builders-challenge`
- Redeploy `vss-blueprint`
