# 17 · Real inference integration (Stage 4)

**Status:**
* Software: implemented and tested against local mock HTTP servers and a synthetic mock engine (`tests/test_stage4_inference.py`, 16 tests).
* Live engines: **not yet run**. No vLLM, SGLang or Ollama server has been measured, so every number this stage can produce is still pending.
* E017 is pre-registered as a hardware protocol (`experiments/E017_real_llm_energy.json`, status `pending_hardware`). `python -m ueic run` refuses it on purpose.

## 1. What it does and why

The simulator counts "successful tasks" with a synthetic workload. Stage 4 measures the real thing on a GPU:
* requests to a real serving engine;
* each request's timing and token counts;
* whether the answer was correct, scored against a benchmark reference;
* the GPU board energy over the same window, from NVML.

It reports energy per correct, on-time result next to the usual J/token, J/request and tokens/s, so it is visible when they disagree.

## 2. Components (`ueic/inference/`)

| File | Role |
|---|---|
| `adapters/base.py` | `GenRequest`, `GenResult`, `ServingAdapter` protocol. One monotonic reference per request, mapped to wall-clock (the NVML telemetry clock) |
| `adapters/openai_compat.py` | Streaming client for `/v1/chat/completions` and `/v1/completions` (SSE, `stream_options.include_usage`) |
| `adapters/vllm_adapter.py` | vLLM (port 8000); `/version` read if present |
| `adapters/sglang_adapter.py` | SGLang through its OpenAI-compatible routes only (port 30000); not yet exercised on a live server |
| `adapters/ollama_adapter.py` | Ollama (port 11434): `/api/chat`, `/api/generate` (NDJSON), `/api/version`, `/api/tags`. Reads server-side `prompt_eval_duration`, `eval_duration` and `load_duration` (nanoseconds) |
| `adapters/mock_adapter.py` | Synthetic in-process engine for tests; every output is labelled `mock` / synthetic |
| `request_tracing.py` | `RequestTrace` (one per item), append-only JSONL writer, Prometheus `/metrics` sampler with configurable gauge names |
| `latency_metrics.py` | TTFT, e2e, queue, inter-chunk, prefill and decode percentiles; requests/s, goodput/s, tokens/s |
| `workload_generator.py` | Dataset loading and converters (GSM8K, HumanEval), smoke set, Poisson/uniform arrivals, open- and closed-loop drivers with retries |
| `quality_evaluation.py` | Scorers: numeric exact match (GSM8K), choice letter, label, ROUGE-L, HumanEval pass@1 (execution opt-in) |
| `energy_accounting.py` | Window energy, idle separation, allocation to requests, metrics per boundary |
| `session.py` | Measurement session: warm-up, traced workload, telemetry, clock guard, summary; idle-power measurement |
| `protocol.py` | E017 operator procedure and the pre-registered selection and holdout analysis |

CLI: `python -m ueic infer probe | run | plan | analyze-e017` (see `python -m ueic --help`).

## 3. Measurement definitions

**Timing (client view unless stated):**
* TTFT = first content chunk − submit. It includes queueing, network and prefill.
* Prefill = the server's value where the engine reports one (Ollama); otherwise TTFT, labelled `timing_source = client`.
* Decode = the server's value where reported; otherwise end − first chunk.
* Inter-chunk latency comes from gaps between streamed chunks. A chunk is not necessarily a token, so `n_chunks` and `completion_tokens` are both stored and their mismatches counted.
* Deadline compliance is measured from the *scheduled* arrival, so client-side queueing counts against it.

**Energy boundaries** (never mixed):

| Boundary | Definition | Evidence |
|---|---|---|
| `gpu_total` | NVML board energy over [first scheduled arrival, last completion]: the cumulative energy counter if it is present and monotonic, else trapezoidal integration of power, plus edge extension | measured (vendor sensor, not independently calibrated) |
| `gpu_dynamic` | gpu_total − P_idle·Δt, with P_idle from a separate idle measurement at the same clocks | measured − measured |
| `wall` | external wall meter (not yet integrated as a source; a planned Stage 9 adapter) | – |
| `facility_est` | a boundary × a stated overhead factor, with its source required | estimated, never measured |

Coverage and the largest sampling gap are reported. A gap over 1 s marks the window incomplete and trips the session guard.

**Allocation to requests** (only `gpu_dynamic` is allocated):
* Idle energy is reported as its own term and never spread over requests.
* `equal_inflight` splits each sampling interval's dynamic energy equally among the requests in flight. Energy with nothing in flight is reported as `unattributed`.
* `token_share` splits in proportion to prompt + completion tokens.
* Both conserve the total (tested). Neither is "true": the first answers "what did concurrency cost", the second "what did tokens cost".

**Useful result** = completed, scored correct against the reference, and within the deadline. Unscored items (for example HumanEval with code execution off) are not useful and not failures. They are counted separately. A model's self-reported confidence is never used.

## 4. Safety

* The package only sends inference requests and reads NVML. A test fails if any file under `ueic/inference/` calls an NVML setter or shells out to `nvidia-smi`.
* `infer plan` *prints* `nvidia-smi -lgc` / `-rgc` lines for the operator to review and run in an administrator shell. The GPU's own power and thermal protection stay active throughout.
* Sessions declare the expected locked clock (`--expect-clock`). If the median SM clock under load differs by more than 30 MHz, the session is marked `guard_failed` and kept, but excluded from arm statistics. This guard was added after M003 attempt 1, where a lock that was not active went unnoticed until analysis.
* HumanEval scoring runs model-written code. It is off by default and should only be enabled in a disposable VM or container.

## 5. E017 in brief (full text in the spec)

* **Arms:**
  * Grid: 2 Ollama models (~3B and ~8B, 4-bit) × 3 clocks (default, f_sus, 0.75 f_sus) × 3 server concurrencies (1, 4, 8).
  * Configurations are selected on GSM8K items 0–99, by fixed rules, under:
    * quality ≥ 0.95 × the best accuracy;
    * ≤ 5% of answers later than 30 s.
  * Arms: B0 default, B1 serving-tuned (the strong baseline), B2 clock-tuned, J joint.
  * The selected arms are evaluated 3 times on held-out items 100–399.
* **Hypotheses:**
  * H1: J is ≥ 10% below B1 in GPU energy per useful result (two-level bootstrap).
  * H2: J meets both constraints on the holdout items.
  * H3: the lowest J/token configuration is not the lowest J/useful configuration.
* The analysis code (`protocol.select_arms`, `protocol.holdout_ratio`) was written and tested on mock sessions before any real session existed.

## 6. How to run

```bash
python -m pytest tests/test_stage4_inference.py
python -m ueic infer probe --engine ollama --model llama3.2:3b            # identity, version, digest
python -m ueic infer run --engine ollama --model llama3.2:3b --items smoke --limit 10 --idle-s 30 --label "smoke"
python -m ueic infer plan experiments/E017_real_llm_energy.json --models <small>,<large> --f-sus <MHz from calib probe>
```

## 7. Limits

* GPU board energy only. CPU, RAM, PSU and cooling are outside the primary boundary until a wall meter is added (Stage 9). The facility boundary is an estimate whenever it is used.
* NVML sampling at 10 Hz smooths sub-100 ms power transients. The energy counter avoids this where the GPU provides it.
* Ollama processes parallel requests differently from vLLM's continuous batching. Results are per engine and not transferable between them.
* Client-side timings include the HTTP stack. On localhost this is small, but it is not zero.
* Benchmarks are not bundled; the operator downloads them from their official sources. Item ranges and file hashes are part of each session's record.
