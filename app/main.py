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
S3_ENDPOINT = os.environ.get("S3_ENDPOINT") or ""
ACCESS_KEY = os.environ.get("ACCESS_KEY") or ""
SECRET_KEY = os.environ.get("SECRET_KEY") or ""
VASTDB_BUCKET = os.environ.get("VASTDB_BUCKET") or ""
USE_SAMPLE = os.environ.get("USE_SAMPLE", "").lower() in ("1", "true", "yes")

CLASS_META = {
    "walkway_violation": ("Walkway violation", "unsafe", "high",
                          "Stop and coach: return to the marked green path"),
    "unauthorized_intervention": ("Unauthorized intervention", "unsafe", "high",
                                  "Stop work until a high-vis authorized vest is worn"),
    "opened_panel_cover": ("Opened panel cover", "unsafe", "severe",
                           "Close the panel cover before leaving the machine"),
    "forklift_overload": ("Forklift overload", "unsafe", "severe",
                          "Stop forklift until the load is 2 blocks or fewer"),
    "parcel_handling": ("Parcel handling", "unsafe", "medium",
                        "Coach: bend knees, keep the load close, two-handed grip"),
    "safe_walkway": ("Safe walkway", "safe", "low",
                     "No action — worker is on the marked green path"),
    "authorized_intervention": ("Authorized intervention", "safe", "low",
                                "No action — authorized vest visible"),
    "closed_panel_cover": ("Closed panel cover", "safe", "low",
                           "No action — panel cover closed"),
    "safe_carrying": ("Safe carrying", "safe", "low",
                      "No action — forklift load is 2 or fewer"),
}

WAND_B_CLASSIFY_PROMPT = """You classify ONE workplace video caption into exactly one class_id.
Reply JSON only: {"class_id":"...","confidence":0-1}

Definitions (follow these, not the class name sound-alikes):
- walkway_violation: person is OFF / outside / not on the marked green path.
- safe_walkway: person is ON or along the marked green path.
- forklift_overload: forklift load count is 3 or more blocks/pallets.
- safe_carrying: forklift load count is 1 or 2, or caption says within the safe limit.
- opened_panel_cover: a machine/electrical PANEL COVER is explicitly OPEN.
- closed_panel_cover: panel cover is explicitly CLOSED and that is the main fact.
- unauthorized_intervention: someone WORKING AT a machine/panel WITHOUT a high-vis vest.
  Walking or sitting in frame without a vest is NOT this class.
- authorized_intervention: someone working at a machine/panel WITH a high-vis vest.
- parcel_handling: person lifting or carrying a parcel/box by hand.

Hard rules:
- If the caption says ON/along the green path, never output walkway_violation.
- If it says two / two stacked / single load / within the safe limit, never output forklift_overload.
- If it says three or more stacked loads, prefer forklift_overload over vest/walkway.
- If PANEL COVER is OPEN, prefer opened_panel_cover over walkway.
- If multiple apply, pick the most severe unsafe class that is explicitly stated.
"""

SEARCHES = [
    ("person walking on or off the marked green path", {"location": "eskisehir_plant"}, ["walkway_violation"]),
    ("OFF THE GREEN PATH person walking outside the marked walkway", {"location": "eskisehir_plant"}, []),
    ("PANEL COVER OPEN on a machine", {"location": "eskisehir_plant"}, []),
    ("worker at a machine panel not wearing a high-visibility vest", {"location": "eskisehir_plant"}, []),
    ("forklift LOAD COUNT 3 or more stacked blocks overload", {"location": "eskisehir_plant"}, []),
    ("forklift LOAD COUNT 2 stacked blocks on the green path", {"location": "eskisehir_plant"}, []),
    ("person carrying or lifting a parcel", {"location": "parcel_demo"}, []),
]

TEAM = [
    {"id": "rivera", "name": "Alex Rivera", "role": "Shift supervisor", "shift": "Days"},
    {"id": "okonkwo", "name": "Sam Okonkwo", "role": "Safety investigator", "shift": "Days"},
    {"id": "chen", "name": "Jordan Chen", "role": "Safety investigator", "shift": "Nights"},
    {"id": "shah", "name": "Priya Shah", "role": "Floor lead", "shift": "Days"},
]
ASSIGN_STATUSES = {"unassigned", "pending", "investigating", "closed"}
ASSIGN_PATH = Path(os.environ.get("ASSIGNMENTS_PATH", "/tmp/warehouse-safety-assignments.json"))

_token = {"value": None, "exp": 0.0}
_cache = {"by_window": {}}
_lock = threading.Lock()
_assign_lock = threading.Lock()

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


def _pack(cid: str, conf: float, reason: str) -> tuple[str, str, str, str, str, float, str]:
    label, btype, sev, action = CLASS_META[cid]
    return cid, label, btype, sev, action, conf, reason


def classify_rules(caption: str, location: str, tags) -> tuple[str, str, str, str, str, float, str]:
    text = (caption or "").lower()
    tagset = {str(t).lower() for t in (tags or [])}
    if location == "parcel_demo" or "parcel" in tagset or "manual_handling" in tagset:
        return _pack("parcel_handling", 0.78, "Clip is tagged as parcel handling")

    three_plus = bool(re.search(
        r"\b(three|four|five|[3-9])\b.{0,40}\b(block|pallet|load|container)s?\b"
        r"|exceeds the safe|more than two",
        text,
    ))
    two_or_fewer = bool(re.search(
        r"\b(two stacked|two blocks|two orange|two pallets|two containers|"
        r"single load|one block|carrying two|within the safe)\b",
        text,
    ))
    panel_open = bool(re.search(r"panel cover is open|opened panel|cover is open", text))
    panel_closed = bool(re.search(
        r"panel cover is closed|panel cover appears to be closed|cover is closed",
        text,
    ))
    on_path = bool(re.search(
        r"\b(on the (marked )?green|along (this |the )?(marked )?green|"
        r"staying within the designated)\b",
        text,
    ))
    off_path = bool(re.search(
        r"\b(off the (marked )?green|outside the green|not on the marked|"
        r"leaving the green|walkway violation)\b",
        text,
    ))
    at_machine = bool(re.search(
        r"\b(seated at a machine|working at a machine|working near a machine|"
        r"operating (the |equipment|the machine)|at a machine or electrical panel|"
        r"working at the controls)\b",
        text,
    ))
    no_vest = bool(re.search(
        r"not wearing a high-visibility|not wearing a high vis|without a (high-)?vis|"
        r"not wearing an? authorization vest",
        text,
    ))
    has_vest = bool(re.search(
        r"(?<!not )wearing a high-visibility|(?<!not )wearing a high vis",
        text,
    ))
    forklift = "forklift" in text

    # Most specific unsafe first — never let vest/walkway steal a counted overload.
    if three_plus and not two_or_fewer:
        return _pack("forklift_overload", 0.88, "Rule: load count is 3 or more")
    if three_plus and ("exceeds" in text or "three" in text):
        return _pack("forklift_overload", 0.84, "Rule: caption says the load exceeds the safe limit")
    if panel_open and not panel_closed:
        return _pack("opened_panel_cover", 0.82, "Rule: caption says the panel cover is open")
    if forklift and two_or_fewer:
        return _pack("safe_carrying", 0.86, "Rule: load count is 2 or fewer")
    if at_machine and no_vest and not has_vest:
        return _pack("unauthorized_intervention", 0.76, "Rule: working at a machine without a high-vis vest")
    if off_path and not on_path:
        return _pack("walkway_violation", 0.84, "Rule: caption says off the green path")
    if at_machine and has_vest:
        return _pack("authorized_intervention", 0.8, "Rule: working at a machine with a high-vis vest")
    if panel_closed and at_machine:
        return _pack("closed_panel_cover", 0.74, "Rule: panel cover is closed")
    if on_path:
        return _pack("safe_walkway", 0.83, "Rule: caption says on the green path")
    return _pack("safe_walkway", 0.3, "Rule: no stronger unsafe cue in the caption")


def classify_wandb(caption: str) -> dict | None:
    if not WANDB_API_KEY or not caption:
        return None
    allowed = ", ".join(CLASS_META)
    body = {
        "model": WANDB_MODEL,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": WAND_B_CLASSIFY_PROMPT + f" class_id must be one of: {allowed}.",
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
        if cid not in CLASS_META:
            return None
        label, btype, sev, action = CLASS_META[cid]
        return {
            "class_id": cid,
            "class_label": label,
            "behavior_type": btype,
            "severity": sev,
            "action": action,
            "confidence": float(parsed.get("confidence") or 0.7),
        }
    except Exception:
        return None


def hit_to_event(h: dict, allow_wandb: bool) -> dict:
    caption = h.get("reasoning_content") or ""
    loc = h.get("location") or ""
    tags = h.get("tags") or []
    cid, label, btype, sev, action, conf, reason = classify_rules(caption, loc, tags)
    reason_source = "rule"
    wandb_used = False
    w = classify_wandb(caption) if allow_wandb else None
    # Strong caption rules win; W&B only fills weak / ambiguous cases.
    if w:
        wandb_used = True
        if conf < 0.65:
            cid, label, btype, sev, action, conf = (
                w["class_id"], w["class_label"], w["behavior_type"],
                w["severity"], w["action"], w["confidence"],
            )
            reason = "W&B classified the caption"
            reason_source = "wandb"
        elif w["class_id"] == cid:
            reason = f"{reason} · W&B agrees"
        else:
            reason = f"{reason} · W&B said {w['class_label']}, rule kept"
    file_label = next((t for t in tags if t in CLASS_META), None)
    if file_label == "walkway_violation" and cid != "walkway_violation":
        reason = "Dataset label is walkway violation. " + reason
    src = h.get("source") or ""
    return {
        "id": src or f"{loc}-{h.get('filename')}",
        "class_id": cid,
        "class_label": label,
        "behavior_type": btype,
        "severity": sev,
        "action": action,
        "confidence": round(conf, 2),
        "label_from_filename": file_label,
        "label_match": None,
        "reason": reason,
        "reason_source": reason_source,
        "location": loc,
        "camera_id": h.get("camera_id") or "",
        "caption": caption,
        "original_video": h.get("original_video") or "",
        "source": src,
        "start_sec": h.get("start_time") or h.get("segment_start_sec") or 0,
        "end_sec": h.get("end_time") or h.get("segment_end_sec") or 0,
        "similarity": h.get("similarity_score"),
        "flagged_at": _flagged_at(h, src),
        "sponsors": {"vast": True, "cosmos": True, "wandb": wandb_used},
    }


def _flagged_at_from_source(src: str) -> str | None:
    m = re.search(r"(20\d{6})_(\d{6})", src or "")
    if not m:
        return None
    d, t = m.group(1), m.group(2)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}T{t[:2]}:{t[2:4]}:{t[4:6]}Z"


def _flagged_at(h: dict, src: str) -> str | None:
    for key in ("created_at", "indexed_at", "timestamp", "upload_time"):
        val = h.get(key)
        if isinstance(val, str) and val:
            return val
    return (
        _flagged_at_from_source(src)
        or _flagged_at_from_source(h.get("filename") or "")
        or _flagged_at_from_source(h.get("original_video") or "")
    )


def _decorate_event(ev: dict) -> dict:
    meta = CLASS_META.get(ev.get("class_id") or "")
    if meta:
        ev["class_label"], ev["behavior_type"], ev["severity"], ev["action"] = meta
    if not ev.get("flagged_at"):
        ev["flagged_at"] = (
            _flagged_at_from_source(ev.get("source") or "")
            or _flagged_at_from_source(ev.get("original_video") or "")
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        )
    return ev


ASSIGN_COLUMNS = None


def _load_json_assignments() -> dict:
    if not ASSIGN_PATH.exists():
        return {}
    try:
        data = json.loads(ASSIGN_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("assignments") or {}


def _save_json_assignments(data: dict) -> None:
    ASSIGN_PATH.parent.mkdir(parents=True, exist_ok=True)
    ASSIGN_PATH.write_text(json.dumps({"assignments": data}))


def _vdb_ready() -> bool:
    return bool(S3_ENDPOINT and ACCESS_KEY and SECRET_KEY and VASTDB_BUCKET)


def _vdb_endpoint() -> str:
    if S3_ENDPOINT.startswith(("http://", "https://")):
        return S3_ENDPOINT
    return f"http://{S3_ENDPOINT}"


def _assignment_table(tx):
    import pyarrow as pa

    global ASSIGN_COLUMNS
    if ASSIGN_COLUMNS is None:
        ASSIGN_COLUMNS = pa.schema([
            ("event_id", pa.utf8()),
            ("assignee_id", pa.utf8()),
            ("status", pa.utf8()),
            ("updated_at", pa.utf8()),
        ])
    bucket = tx.bucket(VASTDB_BUCKET)
    schema = bucket.schema("hackathon", fail_if_missing=False)
    if schema is None:
        schema = bucket.create_schema("hackathon", fail_if_exists=False)
    table = schema.table("safety_assignments", fail_if_missing=False)
    if table is None:
        table = schema.create_table("safety_assignments", columns=ASSIGN_COLUMNS, fail_if_exists=False)
    return table


def _load_vdb_assignments() -> dict:
    import vastdb

    session = vastdb.connect(
        endpoint=_vdb_endpoint(),
        access=ACCESS_KEY,
        secret=SECRET_KEY,
        ssl_verify=False,
    )
    with session.transaction() as tx:
        table = _assignment_table(tx)
        latest: dict = {}
        try:
            reader = table.select(columns=["event_id", "assignee_id", "status", "updated_at"])
            batches = list(reader)
        except Exception:
            batches = []
        for batch in batches:
            for row in batch.to_pylist():
                eid = row.get("event_id") or ""
                if not eid:
                    continue
                prev = latest.get(eid)
                if prev and (prev.get("updated_at") or "") > (row.get("updated_at") or ""):
                    continue
                assignee = row.get("assignee_id") or None
                latest[eid] = {
                    "assignee_id": assignee or None,
                    "status": row.get("status") or "unassigned",
                    "updated_at": row.get("updated_at") or "",
                }
        return latest


def _insert_vdb_assignment(event_id: str, rec: dict) -> None:
    import pyarrow as pa
    import vastdb

    session = vastdb.connect(
        endpoint=_vdb_endpoint(),
        access=ACCESS_KEY,
        secret=SECRET_KEY,
        ssl_verify=False,
    )
    with session.transaction() as tx:
        table = _assignment_table(tx)
        arrow = pa.table(
            {
                "event_id": [event_id],
                "assignee_id": [rec.get("assignee_id") or ""],
                "status": [rec["status"]],
                "updated_at": [rec["updated_at"]],
            },
            schema=ASSIGN_COLUMNS,
        )
        table.insert(arrow)


def _load_assignments() -> tuple[dict, str]:
    if _vdb_ready():
        try:
            return _load_vdb_assignments(), "vastdb"
        except Exception:
            pass
    return _load_json_assignments(), "file"


def _save_assignment_record(event_id: str, rec: dict) -> str:
    store = "file"
    if _vdb_ready():
        try:
            _insert_vdb_assignment(event_id, rec)
            store = "vastdb"
        except Exception:
            store = "file"
    current = _load_json_assignments()
    current[event_id] = rec
    _save_json_assignments(current)
    return store


UPLOAD_WINDOWS = {"1h", "24h", "7d"}


def fetch_vss_events(time_filter: str = "1h") -> dict:
    if not (VSS_URL and VSS_USERNAME and VSS_PASSWORD):
        raise RuntimeError("VSS credentials not set")
    seen = set()
    events = []
    wandb_any = False
    wandb_left = 5
    for query, filters, tags in SEARCHES:
        r = requests.post(
            f"{VSS_URL.rstrip('/')}/api/v1/search",
            headers={**_headers(), "Content-Type": "application/json"},
            json={
                "query": query,
                "top_k": 6,
                "llm_top_n": 1,
                "min_similarity": 0.18,
                "time_filter": time_filter,
                "include_public": True,
                "metadata_filters": filters,
                "tags": tags,
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
        "time_filter": time_filter,
        "events": events,
        "parcel_ready": any(e["location"] == "parcel_demo" for e in events),
        "sponsors": {"vast": True, "cosmos": True, "wandb": wandb_any},
    }


def load_events(force: bool = False, time_filter: str = "1h") -> dict:
    if time_filter not in UPLOAD_WINDOWS:
        time_filter = "1h"
    if USE_SAMPLE:
        data = json.loads(SAMPLE.read_text())
        data["source"] = "sample"
        data["time_filter"] = time_filter
        return data
    now = time.time()
    with _lock:
        slot = _cache["by_window"].get(time_filter)
        if not force and slot and now - slot["at"] < 45:
            return slot["events"]
        try:
            data = fetch_vss_events(time_filter)
        except Exception as exc:
            data = json.loads(SAMPLE.read_text())
            data["source"] = "sample"
            data["time_filter"] = time_filter
            data["error"] = str(exc)
        _cache["by_window"][time_filter] = {"events": data, "at": now}
        return data


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/events")
def events():
    window = request.args.get("window") or "1h"
    if window not in UPLOAD_WINDOWS:
        window = "1h"
    data = dict(load_events(force=request.args.get("refresh") == "1", time_filter=window))
    data["time_filter"] = window
    data["events"] = [_decorate_event(dict(e)) for e in data.get("events") or []]
    return jsonify(data)


@app.get("/team")
def team():
    return jsonify(people=TEAM)


@app.get("/assignments")
def assignments():
    with _assign_lock:
        rows, store = _load_assignments()
        return jsonify(assignments=rows, store=store)


@app.post("/assignments")
def save_assignment():
    body = request.get_json(force=True, silent=True) or {}
    event_id = str(body.get("event_id") or "").strip()
    if not event_id:
        return jsonify(error="event_id required"), 400
    assignee = body.get("assignee_id") or None
    if assignee == "":
        assignee = None
    status = str(body.get("status") or "unassigned")
    known = {p["id"] for p in TEAM}
    if assignee and assignee not in known:
        return jsonify(error="unknown assignee"), 400
    if status not in ASSIGN_STATUSES:
        return jsonify(error="unknown status"), 400
    if status == "unassigned":
        assignee = None
    elif not assignee:
        return jsonify(error="assignee required"), 400
    rec = {
        "assignee_id": assignee,
        "status": status,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with _assign_lock:
        store = _save_assignment_record(event_id, rec)
    return jsonify(assignment=rec, store=store)


@app.get("/detections")
def detections():
    source = request.args.get("source") or ""
    if not source.startswith("s3://"):
        return jsonify(error="source required"), 400
    try:
        r = requests.get(
            f"{VSS_URL.rstrip('/')}/api/v1/videos/detections",
            params={"source": source},
            headers=_headers(),
            timeout=30,
        )
    except requests.RequestException:
        return jsonify(width=0, height=0, frames=[])
    if r.status_code == 404:
        return jsonify(width=0, height=0, frames=[])
    if r.status_code >= 400:
        return jsonify(width=0, height=0, frames=[])
    data = r.json()
    shape = data.get("video_shape") or [0, 0]
    height = int(shape[0]) if shape else 0
    width = int(shape[1]) if len(shape) > 1 else 0
    keep = {"person", "truck", "forklift", "suitcase"}
    frames = []
    for fr in data.get("frames") or []:
        boxes = []
        for det in fr.get("detections") or []:
            label = str(det.get("label") or "")
            if label not in keep:
                continue
            conf = float(det.get("confidence") or 0)
            if conf < 0.4:
                continue
            box = det.get("bbox") or []
            if len(box) != 4:
                continue
            x1, y1, x2, y2 = box
            boxes.append({
                "label": label,
                "conf": round(conf, 2),
                "x": x1,
                "y": y1,
                "w": max(0, x2 - x1),
                "h": max(0, y2 - y1),
            })
        if boxes:
            frames.append({"t": fr.get("time_sec") or 0, "boxes": boxes})
    if len(frames) > 12:
        step = len(frames) / 12
        frames = [frames[int(i * step)] for i in range(12)]
    return jsonify(width=width, height=height, frames=frames)


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


@app.after_request
def _no_store(resp):
    path = request.path
    if path == "/" or path.endswith((".js", ".css", ".html")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def index():
    return send_from_directory(HERE, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
