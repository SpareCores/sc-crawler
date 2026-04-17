"""Workload profile definitions for compound benchmark scoring.

Each workload profile is a weighted combination of benchmark scores that
represents a specific real-world usage pattern. Scores are normalised to [0, 1]
across all servers and aggregated as a weighted mean.

Weights within each workload sum to 1.0.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class BenchmarkEntry(BaseModel):
    """A single benchmark component contributing to a workload profile score."""

    benchmark_id: str
    """The benchmark ID of a BenchmarkScore."""
    weight: float
    """Relative weight of this component. Weights within a workload sum to 1.0."""
    label: str
    """Human-readable description of what this component measures."""
    config_filter: dict[str, Any] | None = None
    """Optional filter applied to the benchmark's config JSON column."""

    model_config = ConfigDict(frozen=True)


class Workload(BaseModel):
    """A named workload profile composed of weighted benchmark entries."""

    name: str
    """Short human-readable name, e.g. 'Web server'."""
    version: str
    """Workload profile version."""
    rationale: str
    """Explanation of which benchmarks were chosen and why."""
    benchmarks: list[BenchmarkEntry]
    """Ordered list of benchmark components with weights."""


WORKLOADS: dict[str, Workload] = {
    "web": Workload(
        name="Web server",
        version="1.0",
        rationale="Primary workloads drivers are HTTP serving speed and throughput, HTML and text processing, TLS termination, and asset compression.",
        benchmarks=[
            # direct web server benchmarks
            BenchmarkEntry(
                benchmark_id="static_web:rps-extrapolated",
                weight=0.25,
                label="Static web RPS (1 kB, 8 conn/vCPU)",
                config_filter={"size": "1k", "connections_per_vcpus": 8.0},
            ),
            BenchmarkEntry(
                benchmark_id="static_web:rps-extrapolated",
                weight=0.15,
                label="Static web RPS (64 kB, 8 conn/vCPU)",
                config_filter={"size": "64k", "connections_per_vcpus": 8.0},
            ),
            BenchmarkEntry(
                benchmark_id="static_web:throughput-extrapolated",
                weight=0.15,
                label="Static web throughput (256 kB, 8 conn/vCPU)",
                config_filter={"size": "256k", "connections_per_vcpus": 8.0},
            ),
            # web rendering proxies
            BenchmarkEntry(
                benchmark_id="geekbench:html5_browser",
                weight=0.10,
                label="Geekbench HTML5 browser (multi-core)",
                config_filter={"cores": "multi"},
            ),
            BenchmarkEntry(
                benchmark_id="geekbench:text_processing",
                weight=0.05,
                label="Geekbench text processing (multi-core)",
                config_filter={"cores": "multi"},
            ),
            # SSL termination
            BenchmarkEntry(
                benchmark_id="openssl",
                weight=0.10,
                label="OpenSSL AES-256-CBC (16 kB blocks)",
                config_filter={"algo": "AES-256-CBC", "block_size": 16384},
            ),
            # asset compression
            BenchmarkEntry(
                benchmark_id="passmark:cpu_encryption_test",
                weight=0.10,
                label="PassMark encryption (AES/SHA/ECDSA)",
            ),
            # string handling
            BenchmarkEntry(
                benchmark_id="passmark:cpu_string_sorting_test",
                weight=0.05,
                label="PassMark string sorting",
            ),
            BenchmarkEntry(
                benchmark_id="passmark:memory_read_cached",
                weight=0.05,
                label="PassMark cached memory reads",
            ),
        ],
    ),
    "compute": Workload(
        name="Compute heavy",
        version="1.0",
        rationale="Number-crunching workload augmenting raw CPU performance stressing, general CPU performance benchmarks, memory bandwidth, and pure math computation speed like floating point, integer, SIMD (AVX/SSE/FMA) operations.",
        benchmarks=[
            # raw CPU performance
            BenchmarkEntry(
                benchmark_id="stress_ng:bestn",
                weight=0.15,
                label="stress-ng div16 best-N cores",
            ),
            BenchmarkEntry(
                benchmark_id="stress_ng:best1",
                weight=0.10,
                label="stress-ng div16 single core",
            ),
            # general CPU performance
            BenchmarkEntry(
                benchmark_id="passmark:cpu_mark",
                weight=0.10,
                label="PassMark CPU Mark (composite)",
            ),
            BenchmarkEntry(
                benchmark_id="geekbench:score",
                weight=0.10,
                label="Geekbench score (multi-core)",
                config_filter={"cores": "multi"},
            ),
            # memory performance
            BenchmarkEntry(
                benchmark_id="bw_mem",
                weight=0.10,
                label="Memory bandwidth (read, 64 MB)",
                config_filter={"operation": "rd", "size": 64.0},
            ),
            # math performance
            BenchmarkEntry(
                benchmark_id="passmark:cpu_floating_point_maths_test",
                weight=0.15,
                label="PassMark floating point",
            ),
            BenchmarkEntry(
                benchmark_id="passmark:cpu_extended_instructions_test",
                weight=0.15,
                label="PassMark AVX/SSE/FMA (SIMD)",
            ),
            BenchmarkEntry(
                benchmark_id="passmark:cpu_integer_maths_test",
                weight=0.10,
                label="PassMark integer math",
            ),
            # potential HPC workloads
            BenchmarkEntry(
                benchmark_id="passmark:cpu_physics_test",
                weight=0.05,
                label="PassMark physics simulation",
            ),
        ],
    ),
    "cache": Workload(
        name="Cache intensive",
        version="1.0",
        rationale="In-memory key-value store workload, mixing direct Redis performance metrics with memory speed and latency benchmarks, and single-core CPU performance profiles.",
        benchmarks=[
            # direct Redis benchmarks
            BenchmarkEntry(
                benchmark_id="redis:rps-extrapolated",
                weight=0.25,
                label="Redis RPS (pipeline=1, SET)",
                config_filter={"operation": "SET", "pipeline": 1.0},
            ),
            BenchmarkEntry(
                benchmark_id="redis:rps-extrapolated",
                weight=0.10,
                label="Redis RPS (pipeline=16, SET)",
                config_filter={"operation": "SET", "pipeline": 16.0},
            ),
            BenchmarkEntry(
                benchmark_id="redis:latency",
                weight=0.10,
                label="Redis latency (pipeline=1, SET)",
                config_filter={"operation": "SET", "pipeline": 1.0},
            ),
            # memory performance benchmarks
            BenchmarkEntry(
                benchmark_id="passmark:memory_latency",
                weight=0.10,
                label="PassMark memory latency (512 MB)",
            ),
            BenchmarkEntry(
                benchmark_id="passmark:memory_mark",
                weight=0.10,
                label="PassMark Memory Mark (composite)",
            ),
            BenchmarkEntry(
                benchmark_id="passmark:memory_read_cached",
                weight=0.10,
                label="PassMark cached memory reads",
            ),
            BenchmarkEntry(
                benchmark_id="bw_mem",
                weight=0.10,
                label="Memory bandwidth (read, 16 MB ~ L3)",
                config_filter={"operation": "rd", "size": 16.0},
            ),
            # CPU performance benchmarks
            BenchmarkEntry(
                benchmark_id="passmark:cpu_single_threaded_test",
                weight=0.10,
                label="PassMark single-thread CPU",
            ),
            BenchmarkEntry(
                benchmark_id="passmark:database_operations",
                weight=0.05,
                label="PassMark in-memory DB operations",
            ),
        ],
    ),
    "llm": Workload(
        name="LLM inference",
        version="1.0",
        rationale="VRAM and memory-bandwidth-bound LLM inference workload, using direct LLM speed benchmarks at two model sizes, and supplementing with raw memory bandwidth, SIMD, and Geekbench vision workloads that exercise ML-style pipelines.",
        benchmarks=[
            # direct LLM speed benchmarks
            BenchmarkEntry(
                benchmark_id="llm_speed:text_generation",
                weight=0.20,
                label="LLM text generation (llama-7b, 128 tok)",
                config_filter={"model": "llama-7b.Q4_K_M.gguf", "tokens": 128},
            ),
            BenchmarkEntry(
                benchmark_id="llm_speed:prompt_processing",
                weight=0.10,
                label="LLM prompt processing (llama-7b, 512 tok)",
                config_filter={"model": "llama-7b.Q4_K_M.gguf", "tokens": 512},
            ),
            BenchmarkEntry(
                benchmark_id="llm_speed:text_generation",
                weight=0.10,
                label="LLM text generation (gemma-2b, 128 tok)",
                config_filter={"model": "gemma-2b.Q4_K_M.gguf", "tokens": 128},
            ),
            # memory performance benchmarks
            BenchmarkEntry(
                benchmark_id="passmark:memory_mark",
                weight=0.10,
                label="PassMark Memory Mark (composite)",
            ),
            BenchmarkEntry(
                benchmark_id="bw_mem",
                weight=0.15,
                label="Memory bandwidth (read, 256 MB)",
                config_filter={"operation": "rd", "size": 256.0},
            ),
            # vector/matrix performance benchmarks
            BenchmarkEntry(
                benchmark_id="passmark:cpu_extended_instructions_test",
                weight=0.10,
                label="PassMark AVX/SSE/FMA (SIMD)",
            ),
            BenchmarkEntry(
                benchmark_id="passmark:cpu_floating_point_maths_test",
                weight=0.05,
                label="PassMark floating point",
            ),
            # specific ML workloads
            BenchmarkEntry(
                benchmark_id="geekbench:object_detection",
                weight=0.10,
                label="Geekbench object detection (multi-core)",
                config_filter={"cores": "multi"},
            ),
            BenchmarkEntry(
                benchmark_id="geekbench:background_blur",
                weight=0.05,
                label="Geekbench background blur (multi-core)",
                config_filter={"cores": "multi"},
            ),
            BenchmarkEntry(
                benchmark_id="geekbench:structure_from_motion",
                weight=0.05,
                label="Geekbench structure-from-motion (multi-core)",
                config_filter={"cores": "multi"},
            ),
        ],
    ),
    "cicd": Workload(
        name="CI/CD build",
        version="1.0",
        rationale="Build performance is driven by single- and multi-core compilation throughput, single-core CPU performance, multi-core compression and text/scripting processing.",
        benchmarks=[
            # compiling software
            BenchmarkEntry(
                benchmark_id="geekbench:clang",
                weight=0.25,
                label="Geekbench Clang compilation (multi-core)",
                config_filter={"cores": "multi"},
            ),
            BenchmarkEntry(
                benchmark_id="geekbench:clang",
                weight=0.10,
                label="Geekbench Clang compilation (single-core)",
                config_filter={"cores": "single"},
            ),
            # single-core and general CPU performance
            BenchmarkEntry(
                benchmark_id="passmark:cpu_single_threaded_test",
                weight=0.15,
                label="PassMark single-thread CPU",
            ),
            BenchmarkEntry(
                benchmark_id="passmark:cpu_compression_test",
                weight=0.10,
                label="PassMark compression",
            ),
            BenchmarkEntry(
                benchmark_id="passmark:cpu_integer_maths_test",
                weight=0.10,
                label="PassMark integer math",
            ),
            BenchmarkEntry(
                benchmark_id="geekbench:text_processing",
                weight=0.10,
                label="Geekbench text processing (multi-core)",
                config_filter={"cores": "multi"},
            ),
            BenchmarkEntry(
                benchmark_id="stress_ng:bestn",
                weight=0.05,
                label="stress-ng div16 best-N cores",
            ),
            # asset compression
            BenchmarkEntry(
                benchmark_id="geekbench:file_compression",
                weight=0.05,
                label="Geekbench file compression (multi-core)",
                config_filter={"cores": "multi"},
            ),
            BenchmarkEntry(
                benchmark_id="compression_text:compress",
                weight=0.05,
                label="Brotli compression (single-thread, level 0)",
                config_filter={
                    "algo": "brotli",
                    "compression_level": 0,
                    "cores": "single",
                },
            ),
            # text processing/scripting
            BenchmarkEntry(
                benchmark_id="passmark:cpu_string_sorting_test",
                weight=0.05,
                label="PassMark string sorting",
            ),
        ],
    ),
}
"""Workload profile definitions keyed by workload ID."""
