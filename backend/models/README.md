# Models

Every model this project has used, which one runs now, and why the others
went. Weights live in this folder, which docker-compose mounts at `/app/models`.
Only the files listed under **In use** are tracked in git. Any other file
dropped here stays ignored (see the root `.gitignore`).

## In use

| File | Model | Role | Config |
|---|---|---|---|
| `yolo26l.pt` | Ultralytics YOLO26-L, COCO-pretrained (80 classes), not fine-tuned | Detects people and bags for the abandonment pipeline | `YOLO_MODEL_PATH="models/yolo26l.pt"` |

- **Source:** official Ultralytics asset `yolo26l.pt` (GitHub releases of `ultralytics/assets`). [model_registry.py](../app/services/model_registry.py) downloads it into this folder if it is missing.
- **Size:** 53,211,173 bytes.
- **SHA-256:** `9fe3c544f2b19bebad7ea41e76d7ad3d88b7c2f10d11d24430c5311f6b32db26`
- **Checkpoint:** dated 2026-01-04 and saved by Ultralytics 8.3.222. The api image runs Ultralytics 8.4.177 with torch 2.11.0+cu128.
- **License:** AGPL-3.0, from Ultralytics. Check this before any commercial or closed-source deployment.
- **Classes watched:**
  - 0 person (owners).
  - 24 backpack, 26 handbag and 28 suitcase, all stored as `bag`.
  - 25 umbrella.
  - 67 cell phone, stored as `mobile_phone`.
  - The renaming comes from `OBJECT_CLASS_IDS` and `CLASS_NAME_MAP` in `backend/.env`.
- **Inference settings:**
  - 640 px input, FP16 on CUDA, class-agnostic NMS.
  - Confidence 0.05. A tracked object needs at least 0.15 to start a track ([trackers/lostfound_bytetrack.yaml](../trackers/lostfound_bytetrack.yaml)).
  - Unconfirmed still objects are followed by box overlap ([tracking_service.py](../app/services/tracking_service.py)).
- **Measured on the 9 labelled clips** (`tools/eval_abandonment.py`, 2026-10-14, `abandon_seconds=5`):
  - 4 of 8 left items caught, 0 false alarms.
  - The misses are items this un-tuned model never or rarely sees: Left-Behined 0002 and 0003, and cctv3. A fourth, Left-Behined 0001, is hidden by passers-by when the clip ends.

Lost-report photo matching uses **no model**: a perceptual hash plus an HSV colour histogram ([visual_similarity.py](../app/utils/visual_similarity.py)).

## Removed

| Model | File | Used for | Period | Why it went |
|---|---|---|---|---|
| Custom `lost_found.pt`: YOLO26-M fine-tuned on 8 classes (0 person, 1 wallet, 2 hand_watch, 3 key, 4 Glasses, 5 bag, 6 umbrella, 7 mobile_phone; 750 images each plus backgrounds) | `lost_found.pt`, 44,050,649 bytes | Detector | 2026-10-14 | Its labels mapped people to class 3 `key`, and it never detected bags left on the floor in CCTV views. Training: base `yolo26m.pt`, 150 epochs, 640 px, batch 4, saved by Ultralytics 8.4.175 on 2026-10-13. The training-script problems behind it were class IDs not remapped when datasets were merged, background images deleted, and images paired with the wrong labels. Deleted 2026-10-16; the original is on the training Google Drive. |
| YOLO11-N, COCO | `yolo11n.pt`, 5,613,764 bytes | Detector | until 2026-10-14 | Too weak on small, distant bags. Replaced by YOLO26-L. |
| OpenCLIP ViT-B-32 (`laion2b_s34b_b79k`) | Hugging Face cache, `models--laion--CLIP-ViT-B-32-laion2B-s34B-b79K` | Embeddings for lost-and-found search | before 2026-10-08 | Search moved to model-free filters (camera, time, type, colour); the embedding columns are dropped at startup ([database.py](../app/core/database.py)). Cache deleted 2026-10-16. |
| DINOv2 ViT-B/14 (`timm/vit_base_patch14_dinov2.lvd142m`) | Hugging Face cache, 346,334,872 bytes | Visual embeddings for matching | until 2026-10-14 | Removed together with CLIP. Cache deleted 2026-10-16. |

## Evaluated, never deployed

| Model | Result | Date |
|---|---|---|
| YOLO11-M and YOLO11-X, COCO | Saw the cctv3 bag on the floor (11-M about 36/80 frames, 11-X 40/80), but no better overall than YOLO26-L, and slower. | 2026-10-14 |
| YOLO26-L at 960 and 1280 px input | 960 px helped Left-Behined 0001 but halved cctv20, at the same cost. 640 px kept. | 2026-10-14 |
| `korzo_model.pt` (YOLOv8, from the Sensors 2025 paper's repo) | Not downloaded. It was trained on 60 outdoor frames, and the paper reports about 28% mAP on airport views. | 2026-10-14 |

## Changing the model

1. Put the weights here and set `YOLO_MODEL_PATH` in `backend/.env`.
2. Set `OBJECT_CLASS_IDS` and `CLASS_NAME_MAP` to the new model's class map. Set `PERSON_CLASS_ID` as well if person isn't class 0.
3. Score it before switching: `python tools/eval_abandonment.py --videos /videos --set abandon_seconds=5`, run in the api container.
4. Recreate the api (`docker compose up -d api`).
5. Add a row to this file, and add the file to the `!backend/models/...` lines in the root `.gitignore` if it should be tracked.

The next step recommended by the Sensors 2025 paper is to fine-tune a small YOLO on CCTV `person` and `luggage` data. The paper's own run went from about 2% to 88% mAP@0.5 on airport views.
