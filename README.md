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

## Evaluation

An evaluation is a check of the app against clips whose class is already known. Each Mendeley file is named with a prefix (`0_te1.mp4`, `3_te2.mp4`, …). That prefix was written onto the upload as a tag. The tag is the ground truth. The app never reads it to choose a class, except the parcel clip, which is routed by its `parcel_demo` location.

| Prefix | Ground-truth tag | Behavior |
|---|---|---|
| `0_` | `walkway_violation` | unsafe |
| `1_` | `unauthorized_intervention` | unsafe |
| `2_` | `opened_panel_cover` | unsafe |
| `3_` | `forklift_overload` | unsafe |
| `4_` | `safe_walkway` | safe |
| `5_` | `authorized_intervention` | safe |
| `6_` | `closed_panel_cover` | safe |
| `7_` | `safe_carrying` | safe |
| `lifting_parcel.mp4` | `parcel_handling` | scored apart; see below |

**Inputs.** 24 plant clips at `location=eskisehir_plant` (3 per class above), ingested with `app/ingest_prompt.txt`. Cosmos writes `reasoning_content` for each segment. YOLO object counts are stored on the segment and are not used in this score.

**Output.** One `class_id` from `classify_rules()` in `app/main.py`, applied to the joined captions of that clip. Weights & Biases is a second opinion in the live queue and is not part of this score: it only replaces the rule when rule confidence is below 0.65.

**Metric.** `label_match` is true when `class_id` equals the upload tag. The same field is on each `GET /events` row for whatever the live searches returned. The table below is the full indexed set (explore, all 24), which is the fair denominator. The on-screen queue is a search sample (`top_k` 6 per query), so its match rate can differ.

**Result, 17 Oct 2026.** 10 of 24 clips match (42%). Safe/unsafe side matches on 11 of 24.

| Class | Matches |
|---|---|
| `forklift_overload` | 3/3 |
| `safe_carrying` | 3/3 |
| `unauthorized_intervention` | 1/3 |
| `opened_panel_cover` | 1/3 |
| `safe_walkway` | 1/3 |
| `authorized_intervention` | 1/3 |
| `walkway_violation` | 0/3 |
| `closed_panel_cover` | 0/3 |
| **All labeled plant clips** | **10/24** |

Forklift load count is the part the prompt asks Cosmos to write as a number, and both load classes are 6/6. The other misses are three kinds: the caption states a different fact than the filename (several behaviors are in one frame, and the dataset has one label); the rule keeps the more severe fact when the caption states two; a negated sentence still matches the positive pattern, so “not on the marked green path” can be read as on the path.

`parcel_demo` had 0 indexed chunks at this run (`lifting_parcel.mp4` was uploaded and was still absent from explore), so the parcel class is not in the 10/24.

To repeat: list `GET /api/v1/videos/explore?location=eskisehir_plant`, read each chunk’s timeline caption, run the rule, compare to the class tag.

## 2-minute demo

Unsafe tab → walkway clip (VAST + Cosmos caption) → forklift overload action → parcel if `parcel_demo` is indexed. Say **VAST, Cosmos, W&B** on screen.
