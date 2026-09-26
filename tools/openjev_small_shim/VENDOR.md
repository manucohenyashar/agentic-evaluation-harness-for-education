# Vendored code

| File | Source | Revision | sha256 |
|---|---|---|---|
| `vendor/openjev_decide.py` | `https://huggingface.co/AlexWortega/openjev/blob/058a6c24911b46d908fbe23541390f8af3df3e4d/code/openjev_decide.py` | `058a6c24911b46d908fbe23541390f8af3df3e4d` | `c3db644745db0a756b7779ef0603e560adf2640f4fd12af3dd7fb2b28492609d` |
| `vendor/modeling_openjev.py` | `https://huggingface.co/AlexWortega/openjev/blob/058a6c24911b46d908fbe23541390f8af3df3e4d/code/modeling_openjev.py` | `058a6c24911b46d908fbe23541390f8af3df3e4d` | `bafb4e454ead6e6b30350ed761ebc78ad3e48a143e7de9fe3403eeb7b6f8d2df` |

- **License:** MIT, as declared by the `AlexWortega/openjev` model card at the same revision.
- **`vendor/openjev_decide.py` is vendored for reference and verification, and is never imported.** `shim.py` reimplements its hypothesis template (`TEMPLATE`, line 31) and its single-window scoring instead of calling `decide()`. Two reasons: the vendor `decide()` splits long states into windows and takes the max over them, which FR-PROV-35 forbids; and the module imports torch at top level. Tests can compare `shim.TEMPLATE` with line 31 textually, and spy the vendor `_windows` function to prove it is never invoked.
- **Updating:** pick a new revision and re-download the file byte-exact from that revision's `raw/` URL. Then update this table and `PINNED_REVISION` in `shim.py` in the same change. A different revision is a different engine build, and it needs its own validation record (FR-CONF-27).
- **Weights** are not vendored. Download `<subfolder>/` at the pinned revision into a local directory and pass it as `--model-dir`. The shim runs with `HF_HUB_OFFLINE=1` and makes no outbound call.

```bash
huggingface-cli download AlexWortega/openjev --revision 058a6c24911b46d908fbe23541390f8af3df3e4d \
  --include "qwen3.5-4b-nli-v5/*" --local-dir /models/openjev-small
python tools/openjev_small_shim/shim.py --model-dir /models/openjev-small --subfolder qwen3.5-4b-nli-v5
```

The 2B fallback build is `--subfolder qwen3.5-2b-nli-v5` (design 1.7.1). Only choose it deliberately, at configuration time.
