"""Warehouse safety queue. Routes at / (Ingress strips /app)."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request, send_from_directory

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "events.sample.json"


def _hydrate_team_config() -> None:
    files = sorted(Path("/config").glob("*.config"))
    if len(files) != 1:
        return
    for line in files[0].read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


_hydrate_team_config()

VSS_URL = os.environ.get("VSS_URL") or os.environ.get("INGRESS_URL") or ""
VSS_USERNAME = os.environ.get("VSS_USERNAME") or os.environ.get("USERNAME") or ""
VSS_PASSWORD = os.environ.get("VSS_PASSWORD") or os.environ.get("PASSWORD") or ""
WANDB_API_KEY = os.environ.get("WANDB_API_KEY") or ""
WANDB_TEAM = os.environ.get("WANDB_TEAM") or ""
WANDB_PROJECT = os.environ.get("WANDB_PROJECT") or ""
WANDB_MODEL = os.environ.get("WANDB_MODEL") or "meta-llama/Llama-3.1-8B-Instruct"
USE_SAMPLE = os.environ.get("USE_SAMPLE", "").lower() in ("1", "true", "yes")

CLASSES = [
    ("walkway_violation", "Walkway violation", "unsafe", "high",
     "Stop and coach: return to the marked green path",
     ("off the green", "outside the green", "walkway violation", "not on the marked", "leaving the green")),
    ("unauthorized_intervention", "Unauthorized intervention", "unsafe", "high",
     "Stop work until a high-vis authorized vest is worn",
     ("without a vest", "no vest", "unauthorized", "not wearing")),
    ("opened_panel_cover", "Opened panel cover", "unsafe", "high",
     "Close the panel cover before leaving the machine",
     ("panel cover open", "opened panel", "cover is open", "door open")),
    ("forklift_overload", "Forklift overload", "unsafe", "high",
     "Stop forklift until the load is 2 blocks or fewer",
     ("three", "3+", "overload", "more than two", "four stacked")),
    ("parcel_handling", "Parcel handling", "unsafe", "medium",
     "Coach: bend knees, keep the load close, two-handed grip",
     ("parcel", "cardboard box", "carrying a box", "lifting a box", "stoop", "bent back")),
    ("safe_walkway", "Safe walkway", "safe", "low",
     "No action — worker is on the marked green path",
     ("along the green", "on the marked green", "staying on the green")),
    ("authorized_intervention", "Authorized intervention", "safe", "low",
     "No action — authorized vest visible",
     ("high-vis", "high vis", "authorization vest", "green vest")),
    ("closed_panel_cover", "Closed panel cover", "safe", "low",
     "No action — panel cover closed",
     ("cover closed", "closed panel", "panel is closed")),
    ("safe_carrying", "Safe carrying", "safe", "low",
     "No action — forklift load is 2 or fewer",
     ("two stacked", "two blocks", "two pallets", "carrying two")),
]

SEARCHES = [
    ("person walking off the marked green walkway", {"location": "eskisehir_plant"}),
    ("opened electrical panel cover", {"location": "eskisehir_plant"}),
    ("worker without a safety vest at a machine panel", {"location": "eskisehir_plant"}),
    ("forklift carrying three or more blocks", {"location": "eskisehir_plant"}),
    ("forklift carrying two blocks on the green path", {"location": "eskisehir_plant"}),
    ("person carrying or lifting a parcel", {"location": "parcel_demo"}),
]

_token = {"value": None, "exp": 0.0}
_cache = {"events": None, "at": 0.0}
_lock = threading.Lock()

app = Flask(__name__, static_folder=str(HERE), static_url_path="")


def _login() -> str:
    now = time.time()
    if _token["value"] and now < _token["exp"]:
        return _token["value"]
    r = requests.post(
        f"{VSS_URL.rstrip('/')}/api/v1/auth/login",
        json={"username": VSS_USERNAME, "password": VSS_PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    tok = r.json()["access_token"]
    _token["value"] = tok
    _token["exp"] = now + 20 * 60
    return tok


def _headers() -> dict:
    return {"Authorization": f"Bearer {_login()}"}


def classify_rules(caption: str, location: str, tags) -> tuple[str, str, str, str, str, float, bool]:
    text = (caption or "").lower()
    tagset = {str(t).lower() for t in (tags or [])}
    if location == "parcel_demo" or "parcel" in tagset or "manual_handling" in tagset:
        cid, label, btype, sev, action, _ = next(c for c in CLASSES if c[0] == "parcel_handling")
        return cid, label, btype, sev, action, 0.7, True
    for cid, label, btype, sev, action, keys in CLASSES:
        if cid in tagset:
            return cid, label, btype, sev, action, 0.8, True
        if any(k in text for k in keys):
            return cid, label, btype, sev, action, 0.62, True
    return "walkway_violation", "Walkway violation", "unsafe", "medium", "Review clip", 0.35, False


def classify_wandb(caption: str) -> dict | None:
    if not WANDB_API_KEY or not caption:
        return None
    allowed = ", ".join(c[0] for c in CLASSES)
    body = {
        "model": WANDB_MODEL,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Classify one workplace video caption. Reply JSON only: "
                    '{"class_id":"...","confidence":0-1}. class_id must be one of: '
                    f"{allowed}."
                ),
            },
            {"role": "user", "content": caption[:1200]},
        ],
    }
    headers = {
        "Authorization": f"Bearer {WANDB_API_KEY}",
        "Content-Type": "application/json",
    }
    if WANDB_TEAM and WANDB_PROJECT:
        headers["OpenAI-Project"] = f"{WANDB_TEAM}/{WANDB_PROJECT}"
    try:
        r = requests.post(
            "https://api.inference.wandb.ai/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=25,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return None
        parsed = json.loads(m.group(0))
        cid = parsed.get("class_id")
        meta = next((c for c in CLASSES if c[0] == cid), None)
        if not meta:
            return None
        return {
            "class_id": meta[0],
            "class_label": meta[1],
            "behavior_type": meta[2],
            "severity": meta[3],
            "action": meta[4],
            "confidence": float(parsed.get("confidence") or 0.7),
        }
    except Exception:
        return None


def hit_to_event(h: dict, allow_wandb: bool) -> dict:
    caption = h.get("reasoning_content") or ""
    loc = h.get("location") or ""
    tags = h.get("tags") or []
    cid, label, btype, sev, action, conf, _ = classify_rules(caption, loc, tags)
    wandb_used = False
    w = classify_wandb(caption) if allow_wandb else None
    if w:
        cid, label, btype, sev, action, conf = (
            w["class_id"], w["class_label"], w["behavior_type"],
            w["severity"], w["action"], w["confidence"],
        )
        wandb_used = True
    src = h.get("source") or ""
    return {
        "id": src or f"{loc}-{h.get('filename')}",
        "class_id": cid,
        "class_label": label,
        "behavior_type": btype,
        "severity": sev,
        "action": action,
        "confidence": round(conf, 2),
        "label_from_filename": next((t for t in tags if t in {c[0] for c in CLASSES}), None),
        "label_match": None,
        "location": loc,
        "camera_id": h.get("camera_id") or "",
        "caption": caption,
        "original_video": h.get("original_video") or "",
        "source": src,
        "start_sec": h.get("start_time") or h.get("segment_start_sec") or 0,
        "end_sec": h.get("end_time") or h.get("segment_end_sec") or 0,
        "similarity": h.get("similarity_score"),
        "sponsors": {"vast": True, "cosmos": True, "wandb": wandb_used},
    }


def fetch_vss_events() -> dict:
    if not (VSS_URL and VSS_USERNAME and VSS_PASSWORD):
        raise RuntimeError("VSS credentials not set")
    seen = set()
    events = []
    wandb_any = False
    wandb_left = 5
    for query, filters in SEARCHES:
        r = requests.post(
            f"{VSS_URL.rstrip('/')}/api/v1/search",
            headers={**_headers(), "Content-Type": "application/json"},
            json={
                "query": query,
                "top_k": 6,
                "llm_top_n": 1,
                "min_similarity": 0.18,
                "time_filter": "all",
                "include_public": True,
                "metadata_filters": filters,
            },
            timeout=60,
        )
        if r.status_code >= 400:
            continue
        for h in r.json().get("results") or []:
            src = h.get("source") or ""
            if src in seen:
                continue
            seen.add(src)
            ev = hit_to_event(h, wandb_left > 0)
            if ev["sponsors"]["wandb"]:
                wandb_left -= 1
                wandb_any = True
            if ev.get("label_from_filename"):
                ev["label_match"] = ev["label_from_filename"] == ev["class_id"]
            events.append(ev)
    events.sort(key=lambda e: (0 if e["behavior_type"] == "unsafe" else 1, -(e.get("similarity") or 0)))
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "vss",
        "events": events,
        "parcel_ready": any(e["location"] == "parcel_demo" for e in events),
        "sponsors": {"vast": True, "cosmos": True, "wandb": wandb_any},
    }


def load_events(force: bool = False) -> dict:
    if USE_SAMPLE:
        data = json.loads(SAMPLE.read_text())
        data["source"] = "sample"
        return data
    now = time.time()
    with _lock:
        if not force and _cache["events"] and now - _cache["at"] < 45:
            return _cache["events"]
        try:
            data = fetch_vss_events()
        except Exception as exc:
            data = json.loads(SAMPLE.read_text())
            data["source"] = "sample"
            data["error"] = str(exc)
        _cache["events"] = data
        _cache["at"] = now
        return data


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/events")
def events():
    return jsonify(load_events(force=request.args.get("refresh") == "1"))


@app.get("/clip")
def clip():
    source = request.args.get("source") or ""
    if not source.startswith("s3://"):
        return jsonify(error="source required"), 400
    token = _login()
    url = f"{VSS_URL.rstrip('/')}/api/v1/videos/stream"
    fwd = {}
    if request.headers.get("Range"):
        fwd["Range"] = request.headers["Range"]
    r = requests.get(
        url,
        params={"source": source, "token": token},
        headers=fwd,
        stream=True,
        timeout=60,
    )
    headers = {
        k: v
        for k, v in r.headers.items()
        if k.lower() in ("content-type", "content-length", "content-range", "accept-ranges")
    }
    return Response(r.iter_content(64 * 1024), status=r.status_code, headers=headers)


@app.get("/")
def index():
    return send_from_directory(HERE, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
