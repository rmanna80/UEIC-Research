"""Pre-register E017 (real LLM energy per useful result). Hardware protocol: it is NOT runnable by
`python -m ueic run`; the operator runs it with `python -m ueic infer plan experiments/E017_real_llm_energy.json`.
Written before any E017 session; no inference session has been run on the user's GPU at registration."""
import json
from pathlib import Path

spec = {
    "key": "E017", "kind": "hardware_protocol", "status": "pending_hardware",
    "title": "Real LLM energy per correct, on-time result: joint model x GPU clock x serving concurrency",
    "research_question": "On one consumer GPU, does choosing the model, the locked GPU clock and the serving "
                         "concurrency jointly lower GPU energy per correct, on-time GSM8K answer, at fixed quality "
                         "and latency constraints, compared with tuning the serving configuration alone?",
    "hypothesis": (
        "Grid: 2 models (operator-chosen instruction models served by Ollama, one ~3B and one ~8B parameters, "
        "4-bit quantised, identities and digests recorded) x 3 GPU clocks (default/unlocked; locked at f_sus = "
        "the sustained clock from `calib probe`; locked at 0.75 f_sus rounded to a supported clock) x 3 server "
        "concurrencies (OLLAMA_NUM_PARALLEL 1, 4, 8; closed-loop clients equal to it). Selection split: GSM8K "
        "test items 0-99; holdout split: items 100-399. Constraints: holdout accuracy >= q_min = 0.95 x the "
        "best selection-split accuracy over all configurations; deadline 30 s per request (from scheduling); "
        "deadline-miss rate <= 5%. Primary metric: GPU-board energy (NVML) over the session window per correct, "
        "on-time result. Arms chosen on the selection split by fixed rules: B0 = larger model, default clock, "
        "concurrency 1; B1 (serving-tuned, the strong baseline) = argmin over model x concurrency at the default "
        "clock; B2 (clock-tuned) = larger model, concurrency 1, argmin over clocks; J (joint) = argmin over all "
        "18 configurations; all argmins subject to the constraints measured on the selection split. "
        "H1: on the holdout split J's energy per useful result is at least 10% lower than B1's (mean over 3 "
        "repeated sessions; 95% bootstrap CI over items and sessions excludes 0 and the point estimate >= 10%). "
        "H2: J meets both constraints on the holdout split. H3: on the selection split the configuration with "
        "the lowest J per output token is not the one with the lowest J per useful result. If J = B1 (clock "
        "control adds nothing) H1 is not supported and that is reported."),
    "null_hypothesis": "Adding GPU clock choice to model and concurrency choice does not lower GPU energy per "
                       "correct, on-time result beyond the serving-tuned baseline.",
    "independent_variables": ["model (2)", "GPU clock (3)", "server concurrency (3)"],
    "dependent_variables": ["GPU energy per correct on-time result (J)", "accuracy", "deadline-miss rate",
                            "J per output token", "J per request", "requests/s", "output tokens/s",
                            "TTFT p50/p95", "e2e p50/p95", "inter-chunk latency p50/p95",
                            "server prefill and decode time (Ollama)", "GPU temperature", "retries", "failed requests"],
    "controlled_variables": ["greedy decoding (temperature 0, seed 0)", "max 512 output tokens",
                             "same prompt template (ueic.inference.workload_generator.GSM8K_INSTRUCTION)",
                             "fan on automatic (recorded)", "2 warm-up requests per session (not scored)",
                             "model kept loaded (keep_alive 30m)", "no other GPU work"],
    "baseline": "B1 serving-tuned (model x concurrency at default clock); also B0 default and B2 clock-tuned",
    "configuration": {
        "engine": "ollama (vLLM optional on Linux/WSL with the same protocol; reported separately)",
        "dataset": "GSM8K test split, official file grade_school_math/data/test.jsonl (openai/grade-school-math); "
                   "convert with ueic.inference.workload_generator.from_gsm8k; record the file's SHA-256",
        "selection_items": [0, 100], "holdout_items": [100, 400],
        "clocks": ["default", "f_sus", "0.75*f_sus"], "concurrency": [1, 4, 8],
        "deadline_s": 30.0, "max_tokens": 512, "q_min_factor": 0.95, "max_deadline_miss": 0.05,
        "repeats_holdout": 3, "idle_measurement_s": 60, "telemetry_interval_s": 0.1},
    "evaluation_criteria": "Per arm: energy per useful result on holdout = sum of session energies / sum of useful "
                           "results over 3 sessions; ratio J/B1 - 1 with a 95% percentile bootstrap (resample items "
                           "within sessions and sessions, 2000 draws, seed 0). Practical threshold 10%.",
    "sample_size": "Selection: 18 configurations x 100 items (1,800 requests). Holdout: up to 4 distinct arms x 3 "
                   "sessions x 300 items. 300 items give an accuracy standard error of about 2.5 points at 70% "
                   "accuracy, below the 5% quality margin.",
    "randomization": "Configuration order within the selection phase and session order in the holdout phase are "
                     "shuffled with seed 17 (`infer plan` prints the order) to spread thermal and background drift "
                     "across arms; item order is fixed.",
    "measurement_boundary": "GPU board energy from NVML (energy counter when available, else integrated power); "
                            "excludes CPU, RAM, PSU losses, chassis fans and any facility cooling. Idle board power "
                            "at each clock is measured separately (60 s) and reported as its own term; facility "
                            "energy is not measured and is not estimated in the primary result.",
    "known_limitations": "One GPU and two models; GSM8K only (one task family); Ollama's scheduling differs from "
                         "vLLM's continuous batching; NVML power is a board sensor with vendor-stated accuracy; "
                         "client-side TTFT includes queueing; prompt caching can shorten prefill for repeated "
                         "prefixes; ambient temperature not controlled.",
    "known_confounders": ["room temperature and GPU temperature drift (recorded)", "background processes",
                          "driver boost behaviour at the default clock", "model load time (excluded by warm-up)"],
    "disclosure": "Before registration no inference session had been run on the user's GPU. Pipeline checks used "
                  "the synthetic mock engine only. The RTX 5070's clock sensitivity (M001) is known: compute-bound "
                  "throughput scales ~linearly with clock, and LLM decode is usually memory-bound.",
    "data_collection": "Each session writes session.json, traces.jsonl, telemetry.csv(+meta), summary.json under "
                       "data/inference/E017/<config>/<timestamp>/ (append-only). Sessions whose clock guard fails "
                       "are kept and excluded from arm statistics, with the reason.",
    "statistics": "Accuracy with Wilson 95% intervals; energy ratios by bootstrap as above; latency percentiles "
                  "from traces. No test of H1-H3 before all holdout sessions are complete.",
    "practical_significance_threshold": 0.10,
    "safety": "UEIC never sets clocks, power limits or fans. Clock locks are applied by the operator with "
              "`nvidia-smi -lgc F,F` in an administrator shell and released with `nvidia-smi -rgc`; the GPU's own "
              "thermal and power protection stay active.",
}
out = Path(__file__).with_name("E017_real_llm_energy.json")
out.write_text(json.dumps(spec, indent=1))
print(out)
