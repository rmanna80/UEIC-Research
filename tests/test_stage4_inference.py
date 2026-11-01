"""Stage 4: inference adapters (against local mock HTTP servers), tracing, drivers, scoring, energy accounting."""
from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from ueic.inference import energy_accounting as ea
from ueic.inference import quality_evaluation as qe
from ueic.inference import workload_generator as wg
from ueic.inference.adapters import GenRequest, make_adapter
from ueic.inference.latency_metrics import summarize_latency
from ueic.inference.request_tracing import make_trace, parse_prometheus, read_traces
from ueic.inference.session import clock_guard, run_session

ROOT = Path(__file__).resolve().parents[1]


class _Handler(BaseHTTPRequestHandler):
    mode = "openai"          # or "ollama"
    fail = False

    def log_message(self, *a):  # silence
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/v1/models":
            return self._json({"data": [{"id": "test-model", "root": "org/test-model"}]})
        if self.path == "/version":
            return self._json({"version": "0.0-test"})
        if self.path == "/api/version":
            return self._json({"version": "0.0-ollama-test"})
        if self.path == "/api/tags":
            return self._json({"models": [{"name": "tiny:1b", "digest": "abc123", "details": {"parameter_size": "1B"}}]})
        self._json({"error": "nope"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if type(self).fail:
            return self._json({"error": "boom"}, 500)
        prompt = body.get("prompt") or body["messages"][-1]["content"]
        m = re.search(r"(\d+) \+ (\d+)", prompt)
        ans = str(int(m.group(1)) + int(m.group(2))) if m else "0"
        pieces = ["The ", "answer ", "is ", "#### ", ans]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if self.path.startswith("/v1") else "application/x-ndjson")
        self.end_headers()
        if self.path.startswith("/v1/"):
            chat = self.path.endswith("chat/completions")
            for p in pieces:
                ch = {"delta": {"content": p}} if chat else {"text": p}
                self.wfile.write(f"data: {json.dumps({'choices': [ch]})}\n\n".encode()); self.wfile.flush()
                time.sleep(0.01)
            fin = {"choices": [{"delta": {}, "finish_reason": "stop"}]} if chat else {"choices": [{"text": "", "finish_reason": "stop"}]}
            self.wfile.write(f"data: {json.dumps(fin)}\n\n".encode())
            self.wfile.write(f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 11, 'completion_tokens': 5}})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            key = "message" if self.path == "/api/chat" else None
            for p in pieces:
                ev = {"message": {"role": "assistant", "content": p}, "done": False} if key else {"response": p, "done": False}
                self.wfile.write((json.dumps(ev) + "\n").encode()); self.wfile.flush()
                time.sleep(0.01)
            self.wfile.write((json.dumps({"done": True, "done_reason": "stop", "prompt_eval_count": 9,
                                          "prompt_eval_duration": 2_000_000, "eval_count": 5,
                                          "eval_duration": 50_000_000, "load_duration": 1_000}) + "\n").encode())


@pytest.fixture()
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    _Handler.fail = False
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.mark.parametrize("chat", [True, False])
def test_vllm_adapter_streams_and_reads_usage(server, chat):
    ad = make_adapter("vllm", server)
    assert ad.model == "test-model" and ad.info()["engine_version"] == "0.0-test"
    r = ad.generate(GenRequest("x", "What is 2 + 3?", chat=chat))
    assert r.status == "ok" and r.text == "The answer is #### 5"
    assert (r.prompt_tokens, r.completion_tokens, r.n_chunks) == (11, 5, 5)
    assert r.t_submit < r.t_first <= r.chunk_times[-1] <= r.t_end
    assert r.finish_reason == "stop" and r.timing_source == "client" and r.server_prefill_s is None


@pytest.mark.parametrize("chat", [True, False])
def test_ollama_adapter_reads_server_timings(server, chat):
    ad = make_adapter("ollama", server, "tiny:1b")
    info = ad.info()
    assert info["engine_version"] == "0.0-ollama-test" and info["model_card"]["digest"] == "abc123"
    r = ad.generate(GenRequest("x", "What is 40 + 2?", chat=chat))
    assert r.status == "ok" and r.text.endswith("42")
    assert r.server_prefill_s == pytest.approx(0.002) and r.server_decode_s == pytest.approx(0.05)
    assert r.timing_source == "server" and (r.prompt_tokens, r.completion_tokens) == (9, 5)


def test_http_errors_and_timeouts_are_recorded_not_raised(server):
    _Handler.fail = True
    r = make_adapter("ollama", server, "tiny:1b").generate(GenRequest("x", "hi"))
    assert r.status == "error" and r.http_status == 500 and r.text == ""
    r = make_adapter("ollama", "http://127.0.0.1:9", "tiny:1b").generate(GenRequest("x", "hi"), timeout_s=1)
    assert r.status in ("error", "timeout") and r.error


def test_trace_derivations_and_deadline_counts_queueing(server):
    ad = make_adapter("vllm", server)
    res = ad.generate(GenRequest("x", "What is 1 + 1?"))
    tr = make_trace(res, "i0", "smoke_arith", res.t_submit - 5.0, 0, deadline_s=1.0)
    assert tr.queue_s == pytest.approx(5.0) and tr.deadline_met is False       # 5 s late at the client
    assert tr.ttft_s > 0 and tr.decode_s > 0 and tr.itl_mean_s > 0


def test_arrivals_seeded_and_closed_loop_counts_retries():
    a, b = wg.arrival_times(50, 2.0, seed=3), wg.arrival_times(50, 2.0, seed=3)
    assert np.array_equal(a, b) and a[0] == 0 and np.all(np.diff(a) >= 0)
    assert np.allclose(np.diff(wg.arrival_times(5, 4.0, process="uniform")), 0.25)
    ad = make_adapter("mock", accuracy=1.0, fail_every=3, decode_s_per_tok=1e-4)
    tr = wg.run_closed_loop(ad, wg.smoke_items(6), 2, max_retries=1, retry_backoff_s=0.0, scorer=qe.make_scorer())
    assert len(tr) == 6 and all(t.status == "ok" for t in tr) and sum(t.retries for t in tr) >= 1
    assert all(t.correct for t in tr)


def test_open_loop_honours_arrivals_and_cap():
    ad = make_adapter("mock", accuracy=1.0, decode_s_per_tok=0.02, out_tokens=5)       # ~0.1 s per request
    tr = wg.run_open_loop(ad, wg.smoke_items(6), rate_per_s=100.0, process="uniform", max_concurrency=1, deadline_s=10)
    assert len(tr) == 6
    assert max(t.queue_s for t in tr) > 0.2        # cap of 1 makes later requests wait at the client
    s = summarize_latency(tr)
    assert s["n_ok"] == 6 and s["n_deadline_missed"] == 0 and s["e2e_p95_s"] > 0


def test_scorers():
    assert qe.extract_final_number("so 3 apples... #### 1,234") == 1234
    assert qe.extract_final_number("I think it's 7. Then 12.") == 12
    assert qe.score_numeric("The answer is 18", "blah\n#### 18")[0] is True
    assert qe.score_numeric("#### 19", "#### 18")[0] is False
    assert qe.extract_choice("The answer is (C).") == "C" and qe.score_choice("Answer: B", "b")[0]
    assert qe.score_label("This review is negative overall", "negative", ["positive", "negative"])[0]
    assert qe.rouge_l_f1("the cat sat", "the cat sat") == 1.0 and qe.rouge_l_f1("a b", "c d") == 0.0
    item = {"entry_point": "add", "code_prompt": "def add(a, b):\n", "test": "def check(f):\n    assert f(2, 3) == 5\n"}
    assert qe.score_humaneval("    return a + b\n", item) == (None, None, "humaneval: code execution disabled (unscored)")
    assert qe.score_humaneval("    return a + b\n", item, allow_code_execution=True)[0] is True
    assert qe.score_humaneval("    return a - b\n", item, allow_code_execution=True)[0] is False
    assert qe.score_humaneval("    while True: pass\n", item, allow_code_execution=True, timeout_s=1)[0] is False


def test_window_energy_counter_and_trapezoid_agree():
    t = np.arange(0, 10.01, 0.1)
    p = np.full(t.size, 100.0)
    e = 1000.0 + 100.0 * t
    a = ea.window_energy(t, p, e, 0.0, 10.0)
    b = ea.window_energy(t, p, None, 0.0, 10.0)
    assert a["method"] == "energy_counter" and b["method"] == "trapezoid_power"
    assert a["E_J"] == pytest.approx(1000.0) and b["E_J"] == pytest.approx(1000.0) and a["complete"]
    gap = ea.window_energy(np.r_[t[:20], t[60:]], np.r_[p[:20], p[60:]], None, 0.0, 10.0)
    assert not gap["complete"] and gap["max_gap_s"] > 3


def _fake_trace(rid, t0, t1, tok):
    from ueic.inference.adapters.base import GenResult
    r = GenResult(rid, "mock", "m", t_submit=t0, t_first=t0 + 0.1, t_end=t1, prompt_tokens=tok, completion_tokens=tok)
    return make_trace(r, rid, "smoke_arith", t0, 0, None)


def test_allocation_conserves_dynamic_energy():
    t = np.arange(0, 10.001, 0.05)
    p = np.where((t >= 2) & (t <= 8), 150.0, 30.0)
    trs = [_fake_trace("a", 2.0, 6.0, 10), _fake_trace("b", 4.0, 8.0, 30)]
    for m in ("equal_inflight", "token_share"):
        al = ea.allocate(trs, t, p, idle_W=30.0, method=m)
        assert sum(al["per_request_J"].values()) + al["unattributed_J"] == pytest.approx(al["dynamic_J"], rel=1e-9)
    eq = ea.allocate(trs, t, p, 30.0, "equal_inflight")["per_request_J"]
    assert eq["a"] == pytest.approx(eq["b"], rel=0.05)            # symmetric overlap -> equal shares
    tok = ea.allocate(trs, t, p, 30.0, "token_share")["per_request_J"]
    assert tok["b"] == pytest.approx(3 * tok["a"])


def test_useful_metrics_count_only_correct_and_on_time():
    trs = [_fake_trace(str(i), 0.0, 1.0, 10) for i in range(4)]
    for t, c, d in zip(trs, [True, True, False, True], [True, False, True, None]):
        t.correct, t.deadline_met = c, d
    m = ea.useful_metrics(trs, 400.0, "gpu_total", price_per_kWh=0.36)
    assert m["n_useful"] == 2 and m["J_per_useful_result"] == 200.0 and m["J_per_request"] == 100.0
    assert m["cost_per_useful_result"] == pytest.approx(200.0 / 3.6e6 * 0.36)


class _FakeLogger:
    """Writes NVML-shaped rows from a synthetic power model (for testing the session pipeline only)."""

    def __init__(self, path, clock=2347):
        self.path, self.clock, self._stop = Path(path), clock, threading.Event()

    def _run(self):
        import csv
        from ueic.telemetry import FIELDS
        with open(self.path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader()
            E = 0.0
            while not self._stop.is_set():
                E += 120.0 * 0.02
                w.writerow({"t_unix": time.time(), "gpu": 0, "power_W": 120.0, "energy_J": E, "temp_C": 60,
                            "sm_clock_MHz": self.clock, "util_gpu_pct": 90, "label": ""})
                f.flush(); time.sleep(0.02)

    def start(self):
        self._t = threading.Thread(target=self._run, daemon=True); self._t.start(); return self

    def stop(self):
        self._stop.set(); self._t.join()


def test_session_end_to_end_with_mock_engine(tmp_path):
    ad = make_adapter("mock", accuracy=1.0, decode_s_per_tok=0.005)
    summ = run_session(ad, wg.smoke_items(8), tmp_path / "s", concurrency=2, deadline_s=5, idle_W=20.0,
                       expect_clock_MHz=2347, logger_factory=lambda p: _FakeLogger(p), price_per_kWh=0.3)
    assert summ["provenance"].startswith("synthetic")
    assert not summ["guard_failed"], summ["guard_problems"]
    m = summ["energy"]["metrics"]
    assert set(m) == {"gpu_total", "gpu_dynamic"} and m["gpu_total"]["n_useful"] == 8
    assert m["gpu_dynamic"]["E_J"] < m["gpu_total"]["E_J"]
    assert len(read_traces(tmp_path / "s" / "traces.jsonl")) == 8
    with pytest.raises(FileExistsError):
        run_session(ad, wg.smoke_items(2), tmp_path / "s", telemetry=False)
    bad = run_session(ad, wg.smoke_items(4), tmp_path / "t", expect_clock_MHz=1800,
                      logger_factory=lambda p: _FakeLogger(p, clock=2347))
    assert bad["guard_failed"] and "median SM clock" in bad["guard_problems"][0]


def test_clock_guard_and_prometheus_parser():
    rows = [{"t_unix": i, "util_gpu_pct": 95, "sm_clock_MHz": 1800} for i in range(10)]
    assert clock_guard(rows, 0, 9, 1800) == [] and clock_guard(rows, 0, 9, 2400)
    assert clock_guard(rows, 0, 9, None) == []
    txt = '# HELP x\nvllm:num_requests_running{model_name="m"} 3\nvllm:num_requests_running{model_name="n"} 2\nother 1\n'
    assert parse_prometheus(txt, ["vllm:num_requests_running", "absent"]) == {"vllm:num_requests_running": 5.0}


def test_e017_is_a_preregistered_protocol_and_not_simulated():
    spec = json.loads((ROOT / "experiments" / "E017_real_llm_energy.json").read_text())
    assert spec["kind"] == "hardware_protocol" and spec["status"] == "pending_hardware"
    from ueic.__main__ import main
    assert main(["run", str(ROOT / "experiments" / "E017_real_llm_energy.json")]) == 2
    from ueic.inference.protocol import plan_e017
    plan = plan_e017(spec, ["small", "large"], 2347)
    assert plan.count("python -m ueic infer run") == 18 and "nvidia-smi -rgc" in plan


def test_inference_package_never_sets_hardware_state():
    forbidden = re.compile(r"nvmlDeviceSet|subprocess\.[a-z_]+\(\s*\[?\s*['\"]nvidia-smi")
    for p in (ROOT / "ueic" / "inference").rglob("*.py"):
        assert not forbidden.search(p.read_text()), p
