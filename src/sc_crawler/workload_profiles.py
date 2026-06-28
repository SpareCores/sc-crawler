"""Workload profile definitions for compound benchmark scoring.

Each workload profile is a weighted combination of benchmark scores that
represents a specific real-world usage pattern. Scores are aggregated as a
weighted average (geometric mean) of benchmark scores compared to their
medians. A score of 1.0 represents a synthetic baseline server with the
median performance of each component benchmark.

Weights within each workload sum to 1.0.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from .table_fields import (
    BenchmarkComponentAggregationMethod,
    BenchmarkComponentMissingPolicy,
    BenchmarkComponentNormalizationMethod,
    Json,
)

_DEFAULT_COMPONENT_PENALTY = 1e-4


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
    on_missing: BenchmarkComponentMissingPolicy = BenchmarkComponentMissingPolicy.IGNORE
    """How to handle a missing or invalid measurement for this component."""
    penalty: float | None = None
    """Substituted normalized ratio when on_missing is PENALIZE."""

    model_config = ConfigDict(frozen=True)

    def effective_penalty(self) -> float:
        """Return the penalty floor used when on_missing is PENALIZE."""
        return self.penalty if self.penalty is not None else _DEFAULT_COMPONENT_PENALTY

    def __json__(self):
        data = dict(sorted(self.model_dump(mode="json").items()))
        if data.get("on_missing") == BenchmarkComponentMissingPolicy.PENALIZE.value:
            if data.get("penalty") is None:
                data["penalty"] = _DEFAULT_COMPONENT_PENALTY
        else:
            data.pop("penalty", None)
        return data


class MeasuredSource(Json):
    kind: Literal["measured"] = "measured"


class ExtrapolatedSource(Json):
    kind: Literal["extrapolated"] = "extrapolated"
    derived_from: list[str]
    note: str | None = None


class CompoundSource(Json):
    kind: Literal["compound"] = "compound"
    aggregation: BenchmarkComponentAggregationMethod
    normalization: BenchmarkComponentNormalizationMethod
    components: list[BenchmarkEntry]

    def __json__(self):
        data = dict(sorted(self.model_dump(mode="json").items()))
        data["components"] = [component.__json__() for component in self.components]
        return data


BenchmarkSource = Annotated[
    Union[MeasuredSource, ExtrapolatedSource, CompoundSource],
    Field(discriminator="kind"),
]


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
        name="Web Server",
        version="2.0",
        rationale="Primary workloads drivers are single-process static HTTP serving speed and throughput, text processing, TLS termination, and asset compression.",
        benchmarks=[
            # direct measurements on static web serving
            BenchmarkEntry(
                benchmark_id="static_web:rps-extrapolated",
                weight=0.30,
                label="Static web RPS (1 kB, 8 conn/vCPU)",
                config_filter={"size": "1k", "connections_per_vcpus": 8.0},
            ),
            BenchmarkEntry(
                benchmark_id="static_web:rps-extrapolated",
                weight=0.20,
                label="Static web RPS (64 kB, 8 conn/vCPU)",
                config_filter={"size": "64k", "connections_per_vcpus": 8.0},
            ),
            BenchmarkEntry(
                benchmark_id="static_web:throughput-extrapolated",
                weight=0.20,
                label="Static web throughput (256 kB, 8 conn/vCPU)",
                config_filter={"size": "256k", "connections_per_vcpus": 8.0},
            ),
            # SSL termination
            BenchmarkEntry(
                benchmark_id="openssl",
                weight=0.20,
                label="OpenSSL AES-256-CBC (16 kB blocks)",
                config_filter={"algo": "AES-256-CBC", "block_size": 16384},
            ),
            # asset compression
            BenchmarkEntry(
                benchmark_id="compression_text:compress",
                weight=0.05,
                label="Gzip compression (multi-core, level 5)",
                config_filter={
                    "algo": "gzip",
                    "compression_level": 1,
                    "cores": "multi",
                },
            ),
            # string handling
            BenchmarkEntry(
                benchmark_id="passmark:cpu_string_sorting_test",
                weight=0.05,
                label="PassMark string sorting",
            ),
        ],
    ),
    "compute": Workload(
        name="Compute Heavy Applications",
        version="2.0",
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
                weight=0.20,
                label="PassMark CPU Mark (composite)",
            ),
            # memory performance
            BenchmarkEntry(
                # TODO migrate to membench with scope:RAM
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
        name="Cache Intensive",
        version="2.0",
        rationale="In-memory key-value store workload, mixing direct Redis performance metrics with memory speed and latency benchmarks, and single-core CPU performance profiles.",
        benchmarks=[
            # direct Redis benchmarks
            BenchmarkEntry(
                benchmark_id="redis:rps-extrapolated",
                weight=0.50,
                label="Redis RPS (pipeline=1, SET)",
                config_filter={"operation": "SET", "pipeline": 1.0},
            ),
            BenchmarkEntry(
                benchmark_id="redis:rps-extrapolated",
                weight=0.20,
                label="Redis RPS (pipeline=16, SET)",
                config_filter={"operation": "SET", "pipeline": 16.0},
            ),
            # memory performance benchmarks
            BenchmarkEntry(
                # NOTE this depends more on the instance family/generation than the size (vCPUs or memory amount)
                benchmark_id="passmark:memory_mark",
                weight=0.10,
                label="PassMark Memory Mark (composite)",
            ),
            BenchmarkEntry(
                # TODO migrate to membench with scope:RAM
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
        ],
    ),
    # TODO add a status to Workload?
    # "database": Workload(
    #     name="Relational Database",
    #     version="2.0",
    #     rationale="Relational database workload (PostgreSQL, MySQL, transactional OLTP). Direct DB operation throughput is the primary driver, followed by memory latency for index lookups and buffer pool access, memory subsystem performance for working-set throughput, and single-thread CPU for query execution.",
    #     benchmarks=[
    #         # TODO extend with Postgres measurements
    #         # NOTE none of the below benchmarks scale well on 32+ vCPUs and
    #         #      rather depends on the instance family/generation than the size (vCPUs or memory amount)
    #         BenchmarkEntry(
    #             # NOTE doesn't scale well on 32+ vCPUs
    #             benchmark_id="passmark:database_operations",
    #             weight=0.35,
    #             label="PassMark in-memory DB operations",
    #         ),
    #         BenchmarkEntry(
    #             benchmark_id="passmark:memory_latency",
    #             weight=0.30,
    #             label="PassMark memory latency (512 MB)",
    #         ),
    #         BenchmarkEntry(
    #             benchmark_id="passmark:memory_mark",
    #             weight=0.20,
    #             label="PassMark Memory Mark (composite)",
    #         ),
    #         BenchmarkEntry(
    #             benchmark_id="passmark:cpu_single_threaded_test",
    #             weight=0.15,
    #             label="PassMark single-thread CPU",
    #         ),
    #     ],
    # ),
    "data_analysis": Workload(
        name="Data Analysis",
        version="2.0",
        rationale="Data analysis and ETL workloads are memory-bandwidth-bound and CPU-throughput-driven. The profile combines general CPU performance and memory bandwidth/latency as the primary drivers, supplemented by single-core compression speed as a proxy for serialisation-heavy ETL tasks.",
        benchmarks=[
            BenchmarkEntry(
                benchmark_id="passmark:cpu_mark",
                weight=0.70,
                label="PassMark CPU Mark (composite)",
            ),
            BenchmarkEntry(
                # NOTE this is more on the instance family/generation than the size (vCPUs or memory amount)
                benchmark_id="compression_text:compress",
                weight=0.10,
                label="Gzip compression (single-core, level 5)",
                config_filter={
                    "algo": "gzip",
                    "compression_level": 5,
                    "cores": "single",
                },
            ),
            BenchmarkEntry(
                # TODO migrate to membench with scope:RAM
                benchmark_id="bw_mem",
                weight=0.10,
                label="Memory bandwidth (read, 64 MB)",
                config_filter={"operation": "rd", "size": 64.0},
            ),
            # NOTE this depends more on the instance family/generation than the size (vCPUs or memory amount)
            BenchmarkEntry(
                benchmark_id="passmark:memory_mark",
                weight=0.10,
                label="PassMark Memory Mark (composite)",
            ),
        ],
    ),
    "llm": Workload(
        name="LLM Inference",
        version="2.0",
        rationale="VRAM and memory-bandwidth-bound LLM inference workload, using direct LLM speed benchmarks at three model sizes, and supplementing with raw memory bandwidth and SIMD performance benchmarks.",
        benchmarks=[
            # direct LLM speed benchmarks from smallest model (to make sure we managed to run at least one model)
            BenchmarkEntry(
                benchmark_id="llm_speed:text_generation",
                weight=0.15,
                label="LLM text generation (SmolLM-135M, 128 tok)",
                config_filter={"model": "SmolLM-135M.Q4_K_M.gguf", "tokens": 128},
                on_missing=BenchmarkComponentMissingPolicy.REQUIRE,
            ),
            BenchmarkEntry(
                benchmark_id="llm_speed:prompt_processing",
                weight=0.15,
                label="LLM prompt processing (SmolLM-135M, 512 tok)",
                config_filter={"model": "SmolLM-135M.Q4_K_M.gguf", "tokens": 512},
                on_missing=BenchmarkComponentMissingPolicy.REQUIRE,
            ),
            BenchmarkEntry(
                benchmark_id="llm_speed:text_generation",
                weight=0.15,
                label="LLM text generation (Llama 7B, 128 tok)",
                config_filter={"model": "llama-7b.Q4_K_M.gguf", "tokens": 128},
                on_missing=BenchmarkComponentMissingPolicy.PENALIZE,
                penalty=1e-4,
            ),
            BenchmarkEntry(
                benchmark_id="llm_speed:prompt_processing",
                weight=0.15,
                label="LLM prompt processing (Llama 7B, 512 tok)",
                config_filter={"model": "llama-7b.Q4_K_M.gguf", "tokens": 512},
                on_missing=BenchmarkComponentMissingPolicy.PENALIZE,
                penalty=1e-4,
            ),
            BenchmarkEntry(
                benchmark_id="llm_speed:text_generation",
                weight=0.15,
                label="LLM text generation (Llama-3.3 70B, 128 tok)",
                config_filter={
                    "model": "Llama-3.3-70B-Instruct-Q4_K_M.gguf",
                    "tokens": 128,
                },
                on_missing=BenchmarkComponentMissingPolicy.PENALIZE,
                penalty=1e-2,
            ),
            BenchmarkEntry(
                benchmark_id="llm_speed:prompt_processing",
                weight=0.15,
                label="LLM prompt processing (Llama-3.3 70B, 512 tok)",
                config_filter={
                    "model": "Llama-3.3-70B-Instruct-Q4_K_M.gguf",
                    "tokens": 512,
                },
                on_missing=BenchmarkComponentMissingPolicy.PENALIZE,
                penalty=1e-2,
            ),
            # memory performance benchmarks
            BenchmarkEntry(
                # TODO migrate to membench with scope:RAM
                benchmark_id="bw_mem",
                weight=0.05,
                label="Memory bandwidth (read, 256 MB)",
                config_filter={"operation": "rd", "size": 256.0},
            ),
            # vector/matrix performance benchmarks
            BenchmarkEntry(
                benchmark_id="passmark:cpu_extended_instructions_test",
                weight=0.025,
                label="PassMark AVX/SSE/FMA (SIMD)",
            ),
            BenchmarkEntry(
                benchmark_id="passmark:cpu_floating_point_maths_test",
                weight=0.025,
                label="PassMark floating point",
            ),
        ],
    ),
    "cicd": Workload(
        name="CI/CD Build",
        version="2.0",
        rationale="Build performance is mainly driven by multi-core compilation throughput, but also bundles single-core compilation speed and general CPU performance, multi-core compression and text/scripting processing.",
        benchmarks=[
            # compiling software
            BenchmarkEntry(
                benchmark_id="geekbench:clang",
                weight=0.50,
                label="Geekbench Clang compilation (multi-core)",
                config_filter={"cores": "multi"},
            ),
            BenchmarkEntry(
                benchmark_id="geekbench:clang",
                weight=0.10,
                label="Geekbench Clang compilation (single-core)",
                config_filter={"cores": "single"},
            ),
            # general CPU performance
            BenchmarkEntry(
                benchmark_id="stress_ng:bestn",
                weight=0.20,
                label="stress-ng div16 best-N cores",
            ),
            BenchmarkEntry(
                benchmark_id="passmark:cpu_integer_maths_test",
                weight=0.05,
                label="PassMark integer math",
            ),
            # asset compression
            BenchmarkEntry(
                benchmark_id="passmark:cpu_compression_test",
                weight=0.05,
                label="PassMark compression",
            ),
            BenchmarkEntry(
                benchmark_id="compression_text:compress",
                weight=0.05,
                label="Brotli compression (multi-core, level 0)",
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
