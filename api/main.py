"""Safety board API. Routes at / (Ingress strips /app). Person A: replace sample with VSS search."""
import json
import os
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SAMPLE = ROOT / "events.sample.json"

app = Flask(__name__, static_folder=str(WEB), static_url_path="")


@app.get("/health")
def health():
    return jsonify(ok=True)


@app.get("/events")
def events():
    data = json.loads(SAMPLE.read_text())
    data["source"] = "sample"
    return jsonify(data)


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
