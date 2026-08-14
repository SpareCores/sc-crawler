from sc_crawler.lookup import (
    _BENCHMARK_FAMILY_INDEPENDENT_NOTE,
    _BENCHMARK_LLM_SPEED_NOTE,
    _BENCHMARK_SINGLE_SESSION_NOTE,
    _BENCHMARK_SINGLE_THREAD_NOTE,
    benchmarks,
)


def _bench(benchmark_id: str):
    return next(b for b in benchmarks if b.benchmark_id == benchmark_id)


def test_geekbench_scaling_notes():
    assert "32 vCPUs" in _bench("geekbench:html5_browser").note
    assert "4 vCPUs" in _bench("geekbench:text_processing").note
    assert "64 vCPUs" in _bench("geekbench:score").note
    assert _bench("geekbench:clang").note is None


def test_passmark_scaling_notes():
    assert "16 vCPUs" in _bench("passmark:memory_mark").note
    assert _bench("passmark:memory_latency").note == _BENCHMARK_FAMILY_INDEPENDENT_NOTE
    assert _bench("passmark:cpu_single_threaded_test").note == (
        _BENCHMARK_SINGLE_THREAD_NOTE
    )
    assert _bench("passmark:cpu_compression_test").note is None


def test_stress_ng_and_bogomips_notes():
    assert _bench("stress_ng:best1").note == _BENCHMARK_SINGLE_THREAD_NOTE
    assert _bench("stress_ng:bestn").note is None
    assert "pseudo-benchmark" in _bench("bogomips").note


def test_throughput_latency_notes():
    redis_latency = _bench("redis:latency").note
    assert "redis:rps" in redis_latency
    assert "standalone benchmark" in redis_latency
    assert "filter" in redis_latency

    static_latency = _bench("static_web:latency").note
    assert "static_web:rps" in static_latency
    assert "filter" in static_latency
    assert "listener bottleneck" not in static_latency

    static_rps = _bench("static_web:rps").note
    assert static_rps is not None
    assert "listener bottleneck" in static_rps


def test_llm_speed_notes():
    text_gen = _bench("llm_speed:text_generation")
    prompt = _bench("llm_speed:prompt_processing")
    assert text_gen.note == _BENCHMARK_LLM_SPEED_NOTE
    assert prompt.note == _BENCHMARK_LLM_SPEED_NOTE
    assert "llama.cpp" in text_gen.note
    assert "vLLM benchmarks" in text_gen.note


def test_pgbench_notes_and_config_fields():
    raw = _bench("pgbench:heavy_read_only")
    single = _bench("pgbench:heavy_read_only:single")
    peak = _bench("pgbench:heavy_read_only:peak")

    assert "integer" in raw.config_fields["concurrency"].lower()
    assert raw.note is None
    assert single.note == _BENCHMARK_SINGLE_SESSION_NOTE
    assert single.note != _BENCHMARK_SINGLE_THREAD_NOTE
    assert peak.note is None
    assert not single.config_fields
    assert not peak.config_fields
