# Shared GraphRAG configuration

`settings.template.yaml` is the sole configuration source for Microsoft
GraphRAG 3.2.0. Run `uv run python -m metallab graph setup` to render two
workspace settings files:

- `data/dirty/graphrag/settings.yaml`
- `data/clean/graphrag/settings.yaml`

The renderer fills chunking from `configs/experiment.yaml`, entity types from
`entity_types.yaml`, and the served embedding model, endpoint and dimensions
from `configs/embeddings/vllm.yaml`. Both settings reference the same prompt
files in this directory. Only file storage paths differ between arms. Each
input directory must contain exactly `stat3.txt` and `tanaka1981.txt`; both
files feed one GraphRAG index in its arm.

The settings contain `${GENERATION_API_BASE_URL}`, `${GENERATION_API_KEY}`,
`${GENERATION_MODEL}` and `${EMBEDDING_API_KEY}` references. Put their values in
an ignored repository-root `.env` or export them in the shell. Never put keys in
this template or `.env.example`. The local vLLM endpoint is configured in
`configs/embeddings/vllm.yaml`.

Run `uv run python -m metallab graph validate` for schema and paired-settings
checks. Add `--runtime` to require the configured credentials and model names.
Validation does not contact the model services; GraphRAG's normal indexing
preflight checks both services before starting the pipeline. Validation reports
are written in each workspace as `validation.json` without credentials.

GraphML and raw extracted graph snapshots are enabled. Index outputs, logs,
cache and vector storage stay inside the corresponding workspace. The
workspaces are generated artifacts and ignored by Git.
