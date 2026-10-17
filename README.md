# Warehouse Safety Agent

Operator **unsafe queue** on team-9 VSS. Canonical code is the `app/` folder (flat, so it fits a K8s ConfigMap).

Clips stay in the shared index. Do not commit `.mp4`s or `/config` secrets.

Deployed demo: [workshop.thecosmoslabs.com](https://workshop.thecosmoslabs.com) → **App**.

## Run

From `app/`:

```bash
pip install -r requirements.txt
# live index (reads INGRESS_URL / USERNAME / PASSWORD / WANDB_* from the VM env)
python main.py
# or mock UI without VSS:
USE_SAMPLE=1 python main.py
```

Open `http://127.0.0.1:8080`.

## Split

| Person | Owns |
|---|---|
| A | `app/main.py` — VSS search, classify, `/events`, `/clip` |
| B | `app/index.html` `styles.css` `app.js` — queue, player, chips |

JSON shape: `CONTRACT.md`.

## 2-minute demo

Unsafe tab → walkway clip (VAST + Cosmos caption) → forklift overload action → parcel if `parcel_demo` is indexed. Say **VAST, Cosmos, W&B** on screen.
