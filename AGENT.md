# Fashion AI Studio — Codex Project Instructions

## Mission
Upgrade this existing Python/Streamlit project into a beginner-friendly, portable AI fashion affiliate video studio. **Implement working code, not just a plan or mock UI.** Inspect `app.py`, `scripts.json`, `requirements.txt`, and `README.md` first; preserve useful code and user data. Communicate in Vietnamese; use English for code and AI prompts.

## User workflow
1. Upload one or many clothing product photos (default: one photo = one independent product; optionally group several photos for one product).
2. Select a saved script and a saved background.
3. Click **Tạo video**; automatically analyze each product, generate five consistent reference images, produce Veo clips, assemble the requested duration with FFmpeg, and save **one MP4 per product**.
4. Preview results, retry a failed product/scene, and download individual videos or a batch ZIP.

## Must-have features
- **Vietnamese UI**, simple mode by default and advanced mode for model/prompt/duration settings.
- **Persistent Background Library:** upload, name, preview, select, version, reuse, delete, export/import. The selected environment (room, rack, props, lighting) must remain consistent across reference images and scenes. Reuse source references where the model supports them; flag drift rather than claiming perfect consistency.
- **Product identity lock:** preserve garment color, shape, fabric, logos, lettering, seams, and proportions; do not invent unseen details. Save structured product and background manifests.
- **Five reference views:** full hanging garment; hand lifting hem; hand pinching fabric; macro fabric/stitching; final full view. Same garment, hanger, rack, hand, lighting, and background. For hanger-only scripts, do not touch fabric.
- **Six editable/versioned scripts:** Fabric inspection 15s `[3,2,3,3,2,2]`; Hanger POV 15s `[3,3,4,3,2]`; Fast Review 15s `[2,3,3,3,4]`; Logo & Stitching 15s `[3,3,4,3,2]`; Premium Minimalist 20s `[4,4,4,4,4]`; Product Showcase 12s `[3,3,3,3]`.
- **AI Settings:** separate OpenAI (analysis/images), Google (images/Veo), and Google Drive connections; selectable *verified supported* model IDs; test connection; store secrets securely, never in source, logs, Git, or ordinary JSON/SQLite plaintext.
- **Batch processing:** persistent SQLite jobs, independent status/retries, safe restart, concurrency and cost limits, mock mode for tests, clear distinction between mock and real generation. Never run paid API calls without user authorization.
- **Video:** portrait 9:16, target H.264 MP4 1080x1920/30fps when possible. Check Veo's real supported clip durations and reference inputs; generate supported durations and trim/assemble with FFmpeg, acknowledging possible continuity limits.
- **Storage:** local-first SQLite and files; optional Google Drive OAuth sync of original images, backgrounds, references, clips, final videos, manifests, and backups. Drive is storage, not compute. Support switching Drive accounts, keys, computers, and hosting without losing the codebase. Provide complete export/import backups excluding credentials.
- **Windows ease of use:** `INSTALL_APP.bat`, `START_APP.bat`, dependency/FFmpeg checks, Vietnamese README. Prepare optional GitHub/free-subdomain deployment documentation, but do not deploy without approval. Free hosting may not support durable long-running video jobs.

## Existing Google Drive folder mapping (initial defaults only)
Root `1gv07p8bIPpiPxsza2eSGDFJdeibB_sk0`; Products `13cFcSbmFW4yhHmsObH4YW8ZPW517xjk7`; Backgrounds `1VvRKrZu5SP2Amm3QB2IXrZL1fOHPXSR5`; References `12juANeUnJmivfnV8dGM0v4ojn6jBVgIZ`; Clips `1-CbtekRfGtAzv3PDAFuTEWUyBW4n4xuT`; Final `1q7G-52w4HKDjtaMM-DmpdyU9Mmlp_Koe`; Projects `1ac9YF8AleSX4K0csjH_pkSVI_R3oQGKG`; Backups `1wcQNT94ApMhsXjFjLMzQgdFeC0BkrLDK`. Never hardcode as immutable; reconnecting a different account must permit a new root/folder mapping and explicit data migration.

## Engineering rules
- Prefer extending the current Streamlit/Python architecture; modularize providers, services, jobs, storage, and UI as useful. Use official documented APIs and SDKs; never invent model capabilities or endpoints.
- Use safe file paths, input validation, timeouts, idempotent job handling, structured error logs without secrets, schema migrations, and clear Vietnamese errors.
- Build a **fully working mock end-to-end pipeline first**, then integrate real APIs behind adapters. Test using mocks, not paid calls. Add unit/integration tests and run them.
- Before destructive changes, external deployment, or paid generation, ask permission. Never ask the user to paste API keys into chat.
- Work incrementally: inspect -> implement -> test -> fix -> document. Do not stop at a proposal. If time-limited, deliver the highest-value working slice and write a precise continuation checklist.

## Completion report
In Vietnamese, report files changed, implemented vs incomplete features, commands/tests run and results, how to launch, what needs credentials, limitations, and next steps. Never claim untested integrations are working.
