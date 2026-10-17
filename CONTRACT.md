# `/events` contract

`GET /events` returns the operator queue. Person B can render `events.sample.json` until the live API is up.

```json
{
  "generated_at": "ISO-8601",
  "source": "sample | vss",
  "events": [
    {
      "id": "string, stable",
      "class_id": "walkway_violation",
      "class_label": "Walkway violation",
      "behavior_type": "unsafe",
      "severity": "high",
      "action": "Coach worker onto the marked green path",
      "confidence": 0.0,
      "label_from_filename": "walkway_violation | null",
      "label_match": true,
      "location": "eskisehir_plant",
      "camera_id": "plant_cam",
      "caption": "Cosmos reasoning text",
      "original_video": "s3://...",
      "source": "s3://...segment....mp4",
      "start_sec": 0,
      "end_sec": 5,
      "similarity": 0.0,
      "sponsors": {
        "vast": true,
        "cosmos": true,
        "wandb": false
      }
    }
  ]
}
```

## `class_id` values

| class_id | type | Mendeley prefix |
|---|---|---|
| `walkway_violation` | unsafe | `0_` |
| `unauthorized_intervention` | unsafe | `1_` |
| `opened_panel_cover` | unsafe | `2_` |
| `forklift_overload` | unsafe | `3_` |
| `safe_walkway` | safe | `4_` |
| `authorized_intervention` | safe | `5_` |
| `closed_panel_cover` | safe | `6_` |
| `safe_carrying` | safe | `7_` |
| `parcel_handling` | unsafe or safe | `lifting_parcel.mp4` |

Default UI filter: `behavior_type=unsafe`.
