# Status: WORKING (2026-08-23, Google Cloud TTS)

Punjabi speech synthesis via **Google Cloud Text-to-Speech**, voice `pa-IN-Chirp3-HD-Puck`.

    fresh render   ~1-3 s    (network round-trip; no model to load)
    cache hit      ~0 s      (file copy)

Replaced AI4Bharat IndicF5 on 2026-08-23. The old numbers are kept below because they were the
reason for the swap: IndicF5 measured **47–79 s per novel phrase** in production — every call
is a fresh process, so each one paid a full torch + model load — and quality was poor enough
that the owner rejected it outright ("really really bad"). A resident-worker design was
considered to fix latency and rejected as real work for a problem the cloud path deletes.

Templated broadcasts — the REI warning, the all-clear, the morning brief skeleton — were
already cache hits and still are. The change is that ad-hoc replies went from "a worker stops
asking" to a couple of seconds.

## What the swap removed

- torch (~2.5 GB), f5-tts, transformers pinning, CUDA index traps, jieba
- three workarounds for bugs in how IndicF5 published its weights (`_build_indicf5` in git
  history if ever needed again)
- the HF_TOKEN gate and the gated-repo setup dance
- reference-clip voice cloning: `prompts/*.wav` and `DEFAULT_REF_TEXT` are gone. The consented
  owner recording is no longer used by anything; it stays on disk untouched.
- the "novel render may take two minutes" timeout headroom (180 s → 60 s)

## What replaced it

- `google-cloud-texttospeech` as the only dependency in the venv
- Application Default Credentials (`gcloud auth application-default login`) — speak.py prints
  exact remediation when they are missing
- cost metered per character: free under 1M chars/month (Chirp3-HD), then $30/1M. Projected
  usage sits far under the allowance; watch it in the console, not in this file.

## Guards worth keeping (unchanged through the swap)

- The plugin fingerprints speak.py's *contents* into its cache key, so changing the voice can
  never leave old-voice audio answering new requests.
- A wav under 1000 bytes is treated as failed synthesis and never delivered — silence is not
  an answer to «ਅੰਦਰ ਨਾ ਜਾਓ».
- Any synthesis failure returns text-only rather than dropping the reply.
