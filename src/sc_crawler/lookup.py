from re import sub
from typing import List

from .table_fields import (
    BenchmarkComponentAggregationMethod,
    BenchmarkComponentNormalizationMethod,
)
from .tables import Benchmark, ComplianceFramework, Country
from .workload_profiles import (
    WORKLOADS,
    CompoundSource,
    ExtrapolatedSource,
    _impact_tooltip,
)

# country codes: https://en.wikipedia.org/wiki/ISO_3166-1#Codes
# mapping: https://github.com/manumanoj0010/countrydetails/blob/master/Countrydetails/data/continents.json  # noqa: E501
country_continent_mapping = {
    "AE": "Asia",
    "AT": "Europe",
    "AU": "Oceania",
    "BE": "Europe",
    "BH": "Asia",
    "BR": "South America",
    "CA": "North America",
    "CH": "Europe",
    "CL": "South America",
    "CN": "Asia",
    "DE": "Europe",
    "DK": "Europe",
    "ES": "Europe",
    "FI": "Europe",
    "FR": "Europe",
    "GB": "Europe",
    "HK": "Asia",
    "ID": "Asia",
    "IE": "Europe",
    "IL": "Asia",
    "IT": "Europe",
    "IN": "Asia",
    "JP": "Asia",
    "KR": "Asia",
    "MY": "Asia",
    "MX": "North America",
    "NL": "Europe",
    "NO": "Europe",
    "NZ": "Oceania",
    "PH": "Asia",
    "PL": "Europe",
    "QA": "Asia",
    "SA": "Asia",
    "SE": "Europe",
    "SG": "Asia",
    "TH": "Asia",
    "TW": "Asia",
    "US": "North America",
    "ZA": "Africa",
}


countries: dict = {
    k: Country(country_id=k, continent=v) for k, v in country_continent_mapping.items()
}
"""Dictionary of [sc_crawler.tables.Country][] instances keyed by the `country_id`."""

# ##############################################################################


compliance_frameworks: dict = {
    "hipaa": ComplianceFramework(
        compliance_framework_id="hipaa",
        name="The Health Insurance Portability and Accountability Act",
        abbreviation="HIPAA",
        description="HIPAA (Health Insurance Portability and Accountability Act) is a U.S. federal law designed to safeguard the privacy and security of individuals' health information, establishing standards for its protection and regulating its use in the healthcare industry.",  # noqa: E501
        homepage="https://www.cdc.gov/phlp/publications/topic/hipaa.html",
    ),
    "soc2t2": ComplianceFramework(
        compliance_framework_id="soc2t2",
        name="System and Organization Controls Level 2 Type 2",
        abbreviation="SOC 2 Type 2",
        description="SOC 2 Type 2 is a framework for assessing and certifying the effectiveness of a service organization's information security policies and procedures over time, emphasizing the operational aspects and ongoing monitoring of controls.",  # noqa: E501
        homepage="https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2",  # noqa: E501
    ),
    "iso27001": ComplianceFramework(
        compliance_framework_id="iso27001",
        name="ISO/IEC 27001",
        abbreviation="ISO 27001",
        description="ISO 27001 is a standard for information security management systems.",  # noqa: E501
        homepage="https://www.iso.org/standard/27001",  # noqa: E501
    ),
}
"""Dictionary of [sc_crawler.tables.ComplianceFramework][] instances keyed by the `compliance_framework_id`."""


def map_compliance_frameworks_to_vendor(
    vendor_id: str, compliance_framework_ids: List[str]
) -> dict:
    """Map compliance frameworks to vendors in a dict.

    Args:
        vendor_id: identifier of a [Vendor][sc_crawler.tables.Vendor]
        compliance_framework_ids: identifier(s) of [`ComplianceFramework`][sc_crawler.tables.ComplianceFramework]

    Returns:
        Array of dictionaries that can be passed to [sc_crawler.insert.insert_items][].
    """
    items = []
    for compliance_framework_id in compliance_framework_ids:
        items.append(
            {
                "vendor_id": vendor_id,
                "compliance_framework_id": compliance_framework_id,
            }
        )
    return items


def _benchmark_plateau_note(vcpus: int) -> str:
    return (
        "This benchmark does not scale well on instances with more than "
        f"{vcpus} vCPUs. Empirical data shows measured scores plateau and "
        "may even degrade as vCPU count increases, so it is not recommended "
        "for evaluating larger instance sizes."
    )


def _benchmark_fixed_workload_note(vcpus: int) -> str:
    return (
        "This benchmark uses a fixed workload size and does not scale with "
        f"vCPU count beyond {vcpus} vCPUs, so it is not recommended for "
        "evaluating larger instance sizes."
    )


_BENCHMARK_FAMILY_INDEPENDENT_NOTE = (
    "This benchmark score is largely independent of vCPU count within an "
    "instance family and mainly reflects hardware generation and memory "
    "characteristics, not instance size."
)

_BENCHMARK_SINGLE_THREAD_NOTE = (
    "This benchmark measures single-threaded CPU performance only, so scores "
    "do not increase with vCPU count beyond one core."
)

_BENCHMARK_SINGLE_SESSION_NOTE = (
    "This benchmark is measured with a single client session, so throughput "
    "does not necessarily grow with vCPU count. On the other hand, it is "
    "not a purely single-threaded metric, as the server may still engage "
    "multiple cores (e.g. parallel request handlers and background processes). "
    "Use it as a per-session efficiency baseline rather than a measure of "
    "instance capacity."
)


def _benchmark_throughput_latency_note(throughput_benchmark_id: str) -> str:
    return (
        "Latency is recorded during the "
        f"{throughput_benchmark_id} run, not as a standalone benchmark. "
        "As it reflects a characteristic of that throughput measurement, "
        "it is not recommended for comparing instances on its own; use it "
        "instead as a filter when interpreting the related throughput scores."
    )


_BENCHMARK_PSEUDO_BENCHMARK_NOTE = (
    "This is a pseudo-benchmark: BogoMips is a kernel-derived timing "
    "calibration value, not a measure of real workload performance. "
    "Scores do not correlate with application throughput and are not "
    "recommended for comparing instances or CPU generations."
)

_BENCHMARK_LLM_SPEED_NOTE = (
    "Throughput depends on model size and hardware. On CPU, smaller models "
    "often top out around 96 vCPUs; larger models hit memory limits sooner. "
    "GPUs are much faster than CPUs for this workload. llama.cpp only uses "
    "multiple GPUs when one card cannot hold the model weights. Extra GPUs "
    "are for fitting the model, not for serving more requests in parallel. "
    "These runs target single-user, low-concurrency inference. For high "
    "concurrency, use the vLLM benchmarks."
)


def _stress_ng_benchmark(method: str, subcategory: str, description: str) -> Benchmark:
    measurement = sub(r"\W+", "_", method)
    return Benchmark(
        benchmark_id="stress_ng:" + measurement,
        name="stress-ng " + method,
        category="stress-ng",
        subcategory=subcategory,
        description=(
            description
            + " The score is the total bogo operations per second (in real time) based on wall clock run time."
        ),
        framework="stress_ng",
        measurement=measurement,
        config_fields={"cores": "Single-Core or Multi-Core stress tests."},
        unit="Bogo operations per second (ops/s)",
    )


def stress_ng_benchmark_id(method: str) -> str | None:
    """Return the benchmark id for a warehoused stress-ng stressor."""
    measurement = sub(r"\W+", "_", method)
    benchmark_id = "stress_ng:" + measurement
    if benchmark_id not in _STRESS_NG_BENCHMARK_IDS:
        return None
    return benchmark_id


_STRESS_NG_METHODS: list[tuple[str, str, str]] = [
    (
        "cpu",
        "CPU integer",
        "Start N workers exercising the CPU by sequentially working through all the different CPU stress methods. Instead of exercising all the CPU stress methods, one can specify a specific CPU stress method with the --cpu-method option.",
    ),
    (
        "branch",
        "CPU integer",
        "Start N workers that randomly branch to 1024 randomly selected locations and hence exercise the CPU branch prediction logic.",
    ),
    (
        "atomic",
        "CPU integer",
        "Start N workers that exercise various GCC __atomic_*() built in operations on 8, 16, 32 and 64 bit integers that are shared among the N workers. This stressor is only available for builds using GCC 4.7.4 or higher. The stressor forces many front end cache stalls and cache references. Note that 32 bit systems do not currently exercise 64 bit integers.",
    ),
    (
        "funccall",
        "CPU integer",
        "Start N workers that call functions of 1 through to 9 arguments. By default all functions with a range of argument types are called, however, this can be changed using the --funccall-method option. This exercises stack function argument passing and re-ordering on the stack and in registers.",
    ),
    (
        "funcret",
        "CPU integer",
        "Start N workers that pass and return by value various small to large data types.",
    ),
    (
        "hash",
        "CPU integer",
        "Start N workers that exercise various hashing functions. Random strings from 1 to 128 bytes are hashed and the hashing rate and chi squared is calculated from the number of hashes performed over a period of time. The chi squared value is the goodnessof-fit measure, it is the actual distribution of items in hash buckets versus the expected distribution of items. Typically a chi squared value close to 1.0 indicates a good hash distribution.",
    ),
    (
        "rotate",
        "CPU integer",
        "Start N workers that exercise 1 bit rotates left and right of unsigned integer variables. The default will rotate four 8, 16, 32, 64 (and if supported 128) bit values 10000 times in a loop per bogo-op.",
    ),
    (
        "str",
        "CPU integer",
        "Start N workers that exercise various libc string functions on random strings.",
    ),
    (
        "wcs",
        "CPU integer",
        "Start N workers that exercise various libc wide character string functions on random strings.",
    ),
    (
        "nop",
        "CPU integer",
        'Start N workers that consume cpu cycles issuing no-op instructions. This stressor is available if the assembler supports the "nop" instruction.',
    ),
    (
        "bitops",
        "CPU integer",
        'Start N workers that perform various calculations using 32 bit integer manipulation operations. Many of these are derived from the Standford "Bit Twiddling Hacks" (Sean Eron Anderson) and Hacker\'s Delight (Henry S. Warren, Jr.).',
    ),
    (
        "intmath",
        "CPU integer",
        "Start N workers that perform addition, subtraction, multiplication, division and modulo math operations on 128, 64, 32, 16 and 8 bit signed integers.",
    ),
    (
        "prime",
        "CPU integer",
        "Start N workers that find prime numbers using the GNU Multiple Precision Arithmetic Library for large integers. The GMP mpz_nextprime function is used to find primes and it uses a probabilistic algorithm to identify primes, but there is a extremely small chance that the values found are non-prime. The search becomes computationally more expensive over time to find larger and larger primes, hence the bogo-op rate will reduce over time.",
    ),
    (
        "fma",
        "CPU float/SIMD",
        "Start N workers that exercise single and double precision floating point multiplication and add operations on arrays of 512 floating point values. More modern processors (Intel Haswell, AMD Bulldozer and Piledriver) and modern C compilers these will be performed by fused-multiply-add (fma3) opcodes. Operations used are:.",
    ),
    (
        "fp",
        "CPU float/SIMD",
        "Start N workers that exercise addition, multiplication and division operations on a range of floating point types. For each type, 8 floating point values are operated upon 65536 times in a loop per bogo op.",
    ),
    (
        "trig",
        "CPU float/SIMD",
        "Start N workers that exercise sin, cos, sincos (where available) and tan libm trigonometric functions using float, double and long double floating point variants. Each function is exercised 10000 times per bogo-operation.",
    ),
    (
        "matrix",
        "CPU float/SIMD",
        "Start N workers that perform various matrix operations on floating point values. Testing on 64 bit x86 hardware shows that this provides a good mix of memory, cache and floating point operations and is an excellent way to make a CPU run hot.",
    ),
    (
        "matrix-3d",
        "CPU float/SIMD",
        "Start N workers that perform various 3D matrix operations on floating point values. Testing on 64 bit x86 hardware shows that this provides a good mix of memory, cache and floating point operations and is an excellent way to make a CPU run hot.",
    ),
    (
        "eigen",
        "CPU float/SIMD",
        "Start N workers that exercise the Eigen C++ matrix library for 2D matrix addition, multiplication, determinant, inverse and transpose operations on long double, double and float matrices. This currently is only available for gcc/g++ builds.",
    ),
    (
        "vecmath",
        "CPU float/SIMD",
        "Start N workers that perform various unsigned integer math operations on various 128 bit vectors. A mix of vector math operations are performed on the following vectors: 16 x 8 bits, 8 x 16 bits, 4 x 32 bits, 2 x 64 bits and where supported 1 x 128 bits. The metrics produced by this mix depend on the processor architecture and the vector math optimisations produced by the compiler.",
    ),
    (
        "vecfp",
        "CPU float/SIMD",
        "Start N workers that exericise floating point (single and double precision) addition, multiplication, division and negation on vectors of 128, 64, 32, 16 and 8 floating point values. The -v option will show the approximate throughput in millions of floating pointer operations per second for each operation. For x86, the gcc/clang target clones attribute has been used to produced vector optimizations for a range of mmx, sse, avx and processor features.",
    ),
    (
        "vecshuf",
        "CPU float/SIMD",
        "Start N workers that shuffle data on various 64 byte vectors comprised of 8, 16, 32, 64 and 128 bit unsigned integers. The integers are shuffled around the vector with 4 shuffle operations per loop, 65536 loops make up one bogo-op of shuffling. The data shuffling rates and shuffle operation rates are logged when using the -v option. This stressor exercises vector load, shuffle/permute, packing/unpacking and store operations.",
    ),
    (
        "vecwide",
        "CPU float/SIMD",
        "Start N workers that perform various 8 bit math operations on vectors of 4, 8, 16, 32, 64, 128, 256, 512, 1024 and 2048 bytes. With the -v option the relative compute performance vs the expected compute performance based on total run time is shown for the first vecwide worker. The vecwide stressor exercises various processor vector instruction mixes and how well the compiler can map the vector operations to the target instruction set.",
    ),
    (
        "monte-carlo",
        "CPU float/SIMD",
        "Start N stressors that compute <pi> and e (Euler's number) using Monte Carlo computational experiments with various random number generators.",
    ),
    (
        "mpfr",
        "CPU float/SIMD",
        "Start N workers that exercise multi-precision floating point operations using the GNU Multi-Precision Floating Point Reliable library (mpfr). Operations computed are as follows:.",
    ),
    (
        "expmath",
        "CPU float/SIMD",
        "Start N workers that exercise various exponential functions with input values 0 to 1 in steps of 0.001; the results are sanity checked to ensure no variation occurs after each round of 10000 computations.",
    ),
    (
        "logmath",
        "CPU float/SIMD",
        "Start N workers that exercise various libm logarithmic functions with input values 1 to 10000. Results are sanity checked to ensure no variation occurs after each round of 10000 computations.",
    ),
    (
        "powmath",
        "CPU float/SIMD",
        "Start N workers that exercise various libm power functions with input values 0 to 1 in steps of 0.001; the results are sanity checked to ensure no variation occurs after each round of 10000 computations.",
    ),
    (
        "hyperbolic",
        "CPU float/SIMD",
        "Start N workers that exercise sinh, cosh, and tanh libm hyperbolic functions using float, double and long double floating point variants. Each function is exercised 10000 times per bogo-operation.",
    ),
    (
        "fractal",
        "CPU float/SIMD",
        "Start N workers that generate 2D fractals. By default a 1024 x 1024 point Mandelbrot set is computed with a maximum of 256 iterations per point in the iterative compute loop. The fractal is computed row by row with multiple rows shared amongst the N fractal stressor instances. Double precision floating point values are used for the points in the complex set of values. Naive computation is used with no special algorithmic shortcuts or interpolation.",
    ),
    (
        "veccmp",
        "CPU float/SIMD",
        "Start N workers that perform various unsigned integer math comparison operations on various 128 bit vectors. A mix of integer vector comparison operations are performed on the following vectors: 16 x 8 bits, 8 x 16 bits, 4 x 32 bits, 2 x 64 bits and if supported 1 x 128 bits. The metrics produced by this mix depend on the processor architecture and the vector math optimisations produced by the compiler.",
    ),
    (
        "crypt",
        "Cryptography",
        "Start N workers that encrypt a 16 character random password using crypt. The password is encrypted using bcrypt bsdicrypt descrypt gost-yescrypt MD5 NT scrypt SHA-1 SHA-256 SHA-512 SunMD5 and yescrypt encryption methods.",
    ),
    (
        "ipsec-mb",
        "Cryptography",
        "Start N workers that perform cryptographic processing using the highly optimized Intel Multi-Buffer Crypto for IPsec library. Depending on the features available, SSE, AVX, AVX and AVX512 CPU features will be used on data encrypted by SHA, DES, CMAC, CTR, HMAC MD5, HMAC SHA1 and HMAC SHA512 cryptographic routines. This is only available for x86-64 modern Intel CPUs.",
    ),
    (
        "zlib",
        "Compression",
        "Start N workers compressing and decompressing random data using zlib. Each worker has two processes, one that compresses random data and pipes it to another process that decompresses the data. This stressor exercises CPU, cache and memory.",
    ),
    (
        "jpeg",
        "Compression",
        "Start N workers that use jpeg compression on a machine generated plasma field image. The default image is a plasma field, however different image types may be selected. The starting raster line is changed on each compression iteration to cycle around the data.",
    ),
    (
        "cache",
        "Memory",
        "Start N workers that perform random wide spread memory read and writes to thrash the CPU cache. The code does not intelligently determine the CPU cache configuration and so it may be sub-optimal in producing hit-miss read/write activity for some processors. Note: to exercise cache misses it is recommended to instead use the matrix-3d stressor using the --matrix-3d-zyx option.",
    ),
    (
        "cacheline",
        "Memory",
        "Start N workers that exercise reading and writing individual bytes in a shared buffer that is the size of a cache line. Each stressor will run 1 or more processes to exercise bytes that are next to each other. The number of per stressor processes run will be scaled so that at least all N bytes of a N byte cache line are exercised. The intent is to try and trigger cacheline corruption, stalls and misses with shared memory accesses.",
    ),
    (
        "l1cache",
        "Memory",
        "Start N workers that exercise the CPU level 1 cache with reads and writes. A cache aligned buffer that is twice the level 1 cache size is read and then written in level 1 cache set sized steps over each level 1 cache set. This is designed to exercise cache block evictions. The bogo-op count measures the number of million cache lines touched. Where possible, the level 1 cache geometry is determined from the kernel, however, this is not possible on some architectures or kernels, so one may need to specify these manually. One can specify 3 out of the 4 cache geometric parameters, these are as follows:.",
    ),
    (
        "memcpy",
        "Memory",
        "Start N workers that copies data to and from a buffer using memcpy and then move the data in the buffer with memmove with 3 different alignments. This will exercise the data cache and memory copying.",
    ),
    (
        "memrate",
        "Memory",
        'Start N workers that exercise a buffer with 1024, 512, 256, 128, 64, 32, 16 and 8 bit reads and writes. 1024, 512 and 256 reads and writes are available with compilers that support integer vectors. x86-64 cpus that support uncached (non-temporal "nt") writes also exercise 128, 64 and 32 writes providing higher write rates than the normal cached writes. x86-64 also exercises repeated string stores using 64, 32, 16 and 8 bit writes. CPUs that support prefetching reads also exercise 64 prefetched "pf" reads. This memory stressor allows one to also specify the maximum read and write rates. The stressors will run at maximum speed if no read or write rates are specified.',
    ),
    (
        "memthrash",
        "Memory",
        "Start N workers that thrash and exercise a 16 MB buffer in various ways to try and trip thermal overrun. Each stressor will start 1 or more threads. The number of threads is chosen so that there will be at least 1 thread per CPU. Note that the optimal choice for N is a value that divides into the number of CPUs.",
    ),
    (
        "stream",
        "Memory",
        'Start N workers exercising a memory bandwidth stressor very loosely based on the STREAM "Sustainable Memory Bandwidth in High Performance Computers" benchmarking tool by John D. McCalpin, Ph.D. This stressor allocates 3 buffers that are at the size of the CPU L3 cache and continually performs rounds of computations on large arrays of double precision floating point numbers.',
    ),
    (
        "vm",
        "Memory",
        "Start N workers continuously calling mmap/munmap and writing to the allocated memory. Note that this can cause systems to trip the kernel OOM killer on Linux systems if not enough physical memory and swap is not available.",
    ),
    (
        "cachehammer",
        "Memory",
        "Start N workers that exercise the cache with a randomized mix of memory read/writes and where possible cache prefetches and cache flushes to random addresses in three memory mapped regions, one of which is shared among all the cache stressors and is the size of the L3 cache, one is local to each instance and is 4 times the L3 cache size and one is a single page mapping that cannot be read or written.",
    ),
    (
        "ptr-chase",
        "Memory",
        "Start N workers that chase memory pointers around page sized nodes of pointers. By default each stressor instance allocates 4096 pages of nodes, each node is an array of pointers that are randomly set to point to other node pages. The stressors follow randomly chosen pointers from each node, chasing around the entire node space. This exercises pointer fetching, pointer dereferencing and is a cache-read exercising stressor. The nodes are allocated with 50% of pages from the heap and 50% from mmap'd memory.",
    ),
    (
        "spinmem",
        "Memory",
        "Start N workers that use a shared memory page to keep two processes synchronized using busy spin loops. One process is a writer that increments a value in memory slot 0 and spin waits for the data to appear in memory slot 1. The other process spin waits for the data to change in slot 0 and copies the changed value into memory slot 1. The stressor benchmarks the time for the transactions to occur between both processes. Note that the optimal number of stressors is half the number of online CPUs in a system. By default 32 bit write/reads are used.",
    ),
    (
        "bsearch",
        "Algorithms",
        "Start N workers that binary search a sorted array of 32 bit integers using bsearch. By default, there are 65536 elements in the array. This is a useful method to exercise random access of memory and processor cache.",
    ),
    (
        "hsearch",
        "Algorithms",
        "Start N workers that search a 80% full hash table using hsearch. By default, there are 8192 elements inserted into the hash table. This is a useful method to exercise access of memory and processor cache.",
    ),
    (
        "qsort",
        "Algorithms",
        "Start N workers that sort 32 bit integers using qsort.",
    ),
    (
        "heapsort",
        "Algorithms",
        "Start N workers that sort 32 bit integers using the BSD heapsort.",
    ),
    (
        "mergesort",
        "Algorithms",
        "Start N workers that sort 32 bit integers using the BSD mergesort.",
    ),
    (
        "bitonicsort",
        "Algorithms",
        "Start N workers that sort 32 bit integers using bitonic sort.",
    ),
    (
        "skiplist",
        "Algorithms",
        "Start N workers that store and then search for integers using a skiplist. By default, 65536 integers are added and searched. This is a useful method to exercise random access of memory and processor cache.",
    ),
    (
        "tree",
        "Algorithms",
        "Start N workers that exercise tree data structures. The default is to add, find and remove 250000 64 bit integers into AVL (avl), Red-Black (rb), Splay (splay), btree and binary trees. The intention of this stressor is to exercise memory and cache with the various tree operations.",
    ),
    (
        "malloc",
        "Algorithms",
        "Start N workers continuously calling malloc, calloc, realloc, posix_memalign, aligned_alloc, memalign and free. By default, up to 65536 allocations can be active at any point, but this can be altered with the --malloc-max option. Allocation, reallocation and freeing are chosen at random; 50% of the time memory is allocation (via one of malloc, calloc or realloc, posix_memalign, aligned_alloc, memalign) and 50% of the time allocations are free'd. Allocation sizes are also random, with the maximum allocation size controlled by the.",
    ),
    (
        "mcontend",
        "Algorithms",
        "Start N workers that produce memory contention read/write patterns. Each stressor runs with 5 threads that read and write to two different mappings of the same underlying physical page. Various caching operations are also exercised to cause sub-optimal memory access patterns. The threads also randomly change CPU affinity to exercise CPU and memory migration stress.",
    ),
    (
        "insertionsort",
        "Algorithms",
        "Start N workers that sort 32 bit integers using insertion sort.",
    ),
    (
        "bubblesort",
        "Algorithms",
        "Start N workers that sort 32 bit integers using bubblesort.",
    ),
    (
        "fibsearch",
        "Algorithms",
        "Start N workers that use a search a sorted array of 32 bit integers using a Fibonacci search. A Fibonacci seaarch is similar to a bsearch except that it uses the Fibonacci series to divide the search into unequal sized spaces. It avoids the costly division operator found in bsearches and examines closer elements on each search step so there is a slight compute and cache advantage over bsearch. By default, there are 65536 elements in the array. This is a useful method to exercise random access of memory and processor cache.",
    ),
    (
        "context",
        "Hypervisor",
        "Start N workers that run three threads that use swapcontext to implement the thread-to-thread context switching. This exercises rapid process context saving and restoring and is bandwidth limited by register and memory save and restore rates.",
    ),
    (
        "switch",
        "Hypervisor",
        "Start N workers that force context switching between two mutually blocking/unblocking tied processes. By default message passing over a pipe is used, but different methods are available.",
    ),
    (
        "clone",
        "Hypervisor",
        "Start N workers that create clones (via the clone and clone3 system calls). This will rapidly try to create a default of 8192 clones that immediately die and wait in a zombie state until they are reaped. Once the maximum number of clones is reached (or clone fails because one has reached the maximum allowed) the oldest clone thread is reaped and a new clone is then created in a first-in first-out manner, and then repeated. A random clone flag is selected for each clone to try to exercise different clone operations. The clone stressor is a Linux only option.",
    ),
    (
        "fork",
        "Hypervisor",
        "Start N workers continually forking children that immediately exit.",
    ),
    (
        "vfork",
        "Hypervisor",
        "Start N workers continually vforking children that immediately exit.",
    ),
    (
        "fault",
        "Hypervisor",
        "Start N workers that generates minor and major page faults.",
    ),
    (
        "tlb-shootdown",
        "Hypervisor",
        "Start N workers that force Translation Lookaside Buffer (TLB) shootdowns. This is achieved by creating up to 16 child processes that all share a region of memory and these processes are shared amongst the available CPUs. The processes adjust the page mapping settings causing TLBs to be force flushed on the other processors, causing the TLB shootdowns.",
    ),
    (
        "mprotect",
        "Hypervisor",
        "Start N workers that exercise changing page protection settings and access memory after each change. 8 processes per worker contend with each other changing page protection settings on a shared memory region of just a few pages to cause TLB flushes. A read and write to the pages can cause segmentation faults and these are handled by the stressor. All combinations of page protection settings are exercised including invalid combinations.",
    ),
    (
        "munmap",
        "Hypervisor",
        "Start N stressors that exercise unmapping of shared non-executable mapped regions of child processes (Linux only). The unmappings map shared memory regions page by page with a prime sized stride that creates many temporary mapping holes. One the unmappings are complete the child will exit and a new one is started. Note that this may trigger segmentation faults in the child process, these are handled where possible by forcing the child process to call _exit.",
    ),
    (
        "null",
        "Hypervisor",
        "Start N workers that exercise /dev/null with write, lseek, ioctl, fcntl, fallocate and fdatasync calls. For just /dev/null write benchmarking use the.",
    ),
    (
        "zero",
        "Hypervisor",
        "Start N workers that exercise /dev/zero with read, lseek, ioctl and mmap calls. For just /dev/zero read benchmarking use the --zero-read option.",
    ),
    (
        "getrandom",
        "Hypervisor",
        "Start N workers that get 8192 random bytes from the /dev/urandom pool using the getrandom system call (Linux) or getentropy (OpenBSD).",
    ),
    (
        "pipe",
        "Hypervisor",
        "Start N workers that perform large pipe writes and reads to exercise pipe I/O. This exercises memory write and reads as well as context switching. Each worker has two processes, a reader and a writer.",
    ),
    (
        "eventfd",
        "Hypervisor",
        "Start N parent and child worker processes that read and write 8 byte event messages between them via the eventfd mechanism (Linux only).",
    ),
    (
        "hrtimers",
        "Hypervisor",
        "Start N workers that exercise high resolution times at a high frequency. Each stressor starts 32 processes that run with random timer intervals of 0.499999 nanoseconds. Running this stressor with appropriate privilege will run these with the SCHED_RR policy.",
    ),
    (
        "clock",
        "Hypervisor",
        "Start N workers exercising clocks and POSIX timers. For all known clock types this will exercise clock_getres, clock_gettime and clock_nanosleep. For all known timers it will create a random duration timer and busy poll this until it expires. This stressor will cause frequent context switching.",
    ),
    (
        "yield",
        "Hypervisor",
        "Start N workers that call sched_yield. This stressor ensures that at least 2 child processes per CPU exercise sched_yield no matter how many workers are specified, thus always ensuring rapid context switching.",
    ),
    (
        "resched",
        "Hypervisor",
        "Start N workers that exercise process rescheduling. Each stressor spawns a child process for each of the positive nice levels and iterates over the nice levels from 0 to the lowest priority level (highest nice value). For each of the nice levels 1024 iterations over 3 non-real time scheduling polices SCHED_OTHER, SCHED_BATCH and SCHED_IDLE are set and a sched_yield occurs to force heavy rescheduling activity. When the -v verbose option is used the distribution of the number of yields across the nice levels is printed for the first stressor out of the N stressors.",
    ),
    (
        "vdso",
        "Hypervisor",
        "Start N workers that repeatedly call each of the system call functions in the vDSO (virtual dynamic shared object). The vDSO is a shared library that the kernel maps into the address space of all user-space applications to allow fast access to kernel data to some system calls without the need of performing an expensive system call.",
    ),
    (
        "usersyscall",
        "Hypervisor",
        "Start N workers that exercise the Linux prctl userspace system call mechanism. A userspace system call is handled by a SIGSYS signal handler and exercised with the system call disabled (ENOSYS) and enabled (via SIGSYS) using prctl PR_SET_SYSCALL_USER_DISPATCH.",
    ),
    (
        "priv-instr",
        "Hypervisor",
        "Start N workers that exercise various architecture specific privileged instructions that cannot be executed by userspace programs. These instructions will be trapped and processed by SIGSEGV or SIGILL signal handlers.",
    ),
    (
        "tsc",
        "Hypervisor",
        "Start N workers that read the Time Stamp Counter (TSC) 256 times per loop iteration (bogo operation). This exercises the tsc instruction for x86, the mftb instruction for ppc64, the rdcycle instruction for RISC-V, the tick instruction on SPARC and the rdtime.d instruction for Loong64.",
    ),
    (
        "x86syscall",
        "Hypervisor",
        "Start N workers that repeatedly exercise the x86-64 syscall instruction to call the getcpu, geteuid, getgid, getpid, gettimeofday and time system calls using the Linux vsyscall handler. Only for Linux.",
    ),
    (
        "cpu-sched",
        "Hypervisor",
        "Start N workers that exercise the scheduler by moving processes to different CPUs. Each worker starts 16 child processes and repeatedly moves the processes to different CPUs and attempts changes their scheduler policy using SCHED_OTHER, SCHED_BATCH, SCHED_IDLE, SCHED_EXT, SCHED_DEADLINE, SCHED_RR and SCHED_FIFO policies. The choice of CPU placement is based on 8 different mechanisms and is changed every second to mix process placements on all the available CPUS. The child processes are run with randomizied nice settings to exercise scheduler prioritization.",
    ),
    (
        "timermix",
        "Hypervisor",
        "Start N workers creating timer and itimer signals at a high rate, this can create a many thousands of timer clock interrupts per second. Each signal that gets handled is counted as a bogo-operation. For timers, the following clocks types (where available) are used: CLOCK_REALTIME, CLOCK_MONOTONIC, CLOCK_PROCESS_CPUTIME_ID, CLOCK_THREAD_CPUTIME_ID, CLOCK_BOOTTIME and CLOCK_TAI. For itimers, the following interval timer types are used: ITIMER_REAL, ITIMER_VIRTUAL and ITIMER_PROF. Some systems may support none or a subset of these timer or itimer types. The freqeuency of the itimers is auto-adjusted to try and maximize the timer interrupt rate.",
    ),
    (
        "mtx",
        "Hypervisor",
        "Start N stressors that exercise ISO C mutex locking and unlocking.",
    ),
]

_STRESS_NG_BENCHMARK_IDS = {
    "stress_ng:" + sub(r"\W+", "_", method) for method, _, _ in _STRESS_NG_METHODS
}


def _geekbenchmark(name: str, description: str, note: str | None = None):
    measurement = sub(r"\W+", "_", name.lower())
    return Benchmark(
        benchmark_id="geekbench:" + measurement,
        name="Geekbench: " + name,
        category="Geekbench",
        description=(
            description
            + "The score is calibrated against a baseline score of 2,500 (Dell Precision 3460 with a Core i7-12700 processor) as per the Geekbench 6 Benchmark Internals."
        ),
        framework="geekbench",
        config_fields={"cores": "Single-Core or Multi-Core performance tests."},
        measurement=measurement,
        note=note,
    )


def _passmark(
    name: str,
    description: str,
    unit: str,
    higher_is_better: bool = True,
    note: str | None = None,
    subcategory: str = "CPU",
):
    measurement = sub(r"\W+", "_", name.lower())
    return Benchmark(
        benchmark_id="passmark:" + measurement,
        framework="passmark",
        measurement=measurement,
        name="PassMark: " + name,
        category="Passmark",
        subcategory=subcategory,
        description=description,
        unit=unit,
        higher_is_better=higher_is_better,
        note=note,
    )


benchmarks: List[Benchmark] = [
    Benchmark(
        benchmark_id="bogomips",
        name="BogoMips",
        category="Other",
        description='A crude measurement of CPU speed by the Linux kernel. This is NOT usable for performance comparisons among different CPUs, but might be useful to check if a processor is in the range of similar processors. As often quoted, BogoMips measures "the number of million times per second a processor can do absolutely nothing".',
        framework="bogomips",
        unit="Millions of instructions per second (MIPS)",
        note=_BENCHMARK_PSEUDO_BENCHMARK_NOTE,
    ),
    Benchmark(
        benchmark_id="bw_mem",
        name="Memory bandwidth (bw_mem)",
        category="Memory bandwidth",
        subcategory="bw_mem",
        description="bw_mem allocates twice the specified amount of memory, zeros it, and then times the copying of the first half to the second half. Results are reported in megabytes moved per second (MB/sec). bw_mem is provided by lmbench. For more details, see the man pages.",
        framework="bw_mem",
        config_fields={
            "operation": "The type of measurement: 'rd' measures the time to read data into the processor, 'wr' measures the time to write data to memory, and 'rdwr' measures the time to read data into memory and then write data to the same memory location.",
            "size": "Amount of memory to be used in MB",
        },
        unit="Megabytes per second (MB/sec)",
    ),
    Benchmark(
        benchmark_id="compression_text:ratio",
        name="Compression ratio",
        category="Compression algos",
        description="Measures the compression ratio while compressing the dickens.txt of the Silesia corpus (10 MB uncompressed) using various algorithms, compression levels and other extra arguments.",
        framework="compression_text",
        config_fields={
            "algo": "Compression algorithm, e.g. brotli or bz2.",
            "compression_level": "Compression level/quality/level.",
            "cores": "Single-Core or Multi-Core compression tests.",
            "block_size": "Block size",
        },
        measurement="ratio",
        higher_is_better=False,
    ),
    Benchmark(
        benchmark_id="compression_text:compress",
        name="Compression bandwidth",
        category="Compression algos",
        description="Measures the compression bandwidth (bytes/second) on the dickens.txt of the Silesia corpus (10 MB uncompressed) using various algorithms, compression levels and other extra arguments.",
        framework="compression_text",
        config_fields={
            "algo": "Compression algorithm, e.g. brotli or bz2.",
            "compression_level": "Compression level/quality/level.",
            "cores": "Single-Core or Multi-Core compression tests.",
            "block_size": "Block size",
        },
        measurement="compress",
        unit="Bytes per second (Bps)",
    ),
    Benchmark(
        benchmark_id="compression_text:decompress",
        name="Decompression bandwidth",
        category="Compression algos",
        description="Measures the decompression bandwidth (bytes/second) on the compressed dickens.txt of the Silesia corpus (10 MB uncompressed) using various algorithms, compression levels and other extra arguments.",
        framework="compression_text",
        config_fields={
            "algo": "Compression algorithm, e.g. brotli or bz2.",
            "compression_level": "Compression level/quality/level.",
            "cores": "Single-Core or Multi-Core compression tests.",
            "block_size": "Block size",
        },
        measurement="decompress",
        unit="Bytes per second (Bps)",
    ),
    _geekbenchmark(
        "Score",
        "Composite score using the weighted arithmetic mean of the subsection scores, which are computed using the geometric mean of the related scores.",
        note=_benchmark_plateau_note(64),
    ),
    _geekbenchmark(
        "File Compression",
        "Compresses and decompresses the Ruby 3.1.2 source archive (a 75 MB archive with 9841 files) using LZ4 and ZSTD on an in-memory encrypted file system. It also verifies the files using SHA1.",
        note=_benchmark_plateau_note(32),
    ),
    _geekbenchmark(
        "Navigation",
        "Generates 24 different routes between a sequence of locations on two OpenStreetMap maps (one for a small city, one for a large city) using Dijkstra's algorithm.",
        note=_benchmark_plateau_note(32),
    ),
    _geekbenchmark(
        "HTML5 Browser",
        "Opens and renders web pages (8 in single-core mode, 32 in multi-core mode) using a headless web browser.",
        note=_benchmark_plateau_note(32),
    ),
    _geekbenchmark(
        "PDF Renderer",
        "Opens complex PDF documents (4 in single-core mode, 16 in multi-core mode) of park maps from the American National Park Service (sizes from 897 kB to 1.5 MB) with large vector images, lines and text.",
        note=_benchmark_plateau_note(32),
    ),
    _geekbenchmark(
        "Photo Library",
        "Categorizes and tags photos (16 in single-core mode, 64 in multi-core mode) based on the objects that they contain. The workload performs JPEG decompression, thumbnail generation, image transformations, image classification (using MobileNet 1.0), and storing data in SQLite.",
    ),
    _geekbenchmark(
        "Clang",
        "Compiles files (8 in single-core mode, 96 in multi-core mode) of the Lua interpreter using Clang and the musl libc as the C standard library for the compiled files.",
    ),
    _geekbenchmark(
        "Text Processing",
        "Loads 190 markdown files, parses the contents using regular expressions, stores metadata in a SQLite database, and exports the content to a different format on an in-memory encrypted file system, using a mix of C++ and Python.",
        note=_benchmark_fixed_workload_note(4),
    ),
    _geekbenchmark(
        "Asset Compression",
        "Compresses 16 texture images and geometry files using ASTC, BC7, DXTC, and Draco.",
    ),
    _geekbenchmark(
        "Object Detection",
        "Detects and classifies objects in 300x300 pixel photos (16 in single-core mode, 64 in multi-core mode) using the MobileNet v1 SSD convolutional neural network.",
        note=_benchmark_plateau_note(32),
    ),
    _geekbenchmark(
        "Background Blur",
        "Separates and blurs the background of 10 frames in a 1080p video, using DeepLabV3+.",
        note=_benchmark_plateau_note(32),
    ),
    _geekbenchmark(
        "Horizon Detection",
        "Detects and straightens uneven or crooked horizon lines in a 48MP photo to make it look more realistic, using the Canny edge detector and the Hough transform.",
    ),
    _geekbenchmark(
        "Object Remover",
        "Removes an object (using a mask) from a 3MP photo, and fills in the gap left behind using the iterative PatchMatch Inpainting approach (Barnes et al. 2009).",
        note=_benchmark_plateau_note(32),
    ),
    _geekbenchmark(
        "HDR",
        "Blends six 16MP SDR photos to create a single HDR photo, using a recovery process and radiance map construction (Debevec and Malik 1997), and a tone mapping algorithm (Reinhard and Devlin 2005).",
    ),
    _geekbenchmark(
        "Photo Filter",
        "Applies colour and blur filters, level adjustments, cropping, scaling, and image compositing filters to 10 photos that range in size from 3 MP to 15 MP.",
        note=_benchmark_plateau_note(32),
    ),
    _geekbenchmark(
        "Ray Tracer",
        "Renders the Blender BMW scene using a custom ray tracer built with the Intel Embree ray tracing library.",
    ),
    _geekbenchmark(
        "Structure from Motion",
        "Generates 3D geometry by constructing the coordinates of the points that are visible in nine 2D images of the same scene.",
    ),
    Benchmark(
        benchmark_id="openssl",
        name="OpenSSL speed",
        category="Cryptography",
        subcategory="OpenSSL",
        description="Measures the performance of OpenSSL's selected hash functions and block ciphers with different block sizes of data.",
        framework="openssl",
        config_fields={
            "algo": "Hash or block cipher algorithm, e.g. sha256 or aes-256-cbc.",
            "block_size": "Block size (byte).",
        },
        unit="Bytes per second (Bps)",
    ),
    Benchmark(
        benchmark_id="stress_ng:cpu_all",
        name="stress-ng CPU all",
        category="stress-ng",
        description="Stress the CPU with all available methods supported by stress-ng, and count the total bogo operations per second (in real time) based on wall clock run time. The stress methods include bit operations, recursive calculations, integer divisions, floating point operations, matrix multiplication, stats, trigonometric, and hash functions. Note that this is to be deprecated in favor of stress_ng:div16.",
        framework="stress_ng",
        measurement="cpu_all",
        config_fields={"cores": "Stressing a single core or all cores."},
        unit="Bogo operations per second (ops/s)",
    ),
    Benchmark(
        benchmark_id="stress_ng:div16",
        name="stress-ng div16",
        category="stress-ng",
        description="Stress the CPU with the div16 method of stress-ng using a varying number of vCPU cores, and count the measured maximum total bogo operations per second (in real time) based on wall clock run time.",
        framework="stress_ng",
        measurement="div16",
        config_fields={"cores": "Number of CPU cores stressed."},
        unit="Bogo operations per second (ops/s)",
    ),
    Benchmark(
        benchmark_id="stress_ng:best1",
        name="stress-ng div16 single-core",
        category="stress-ng",
        description="Stress a single vCPU core with the div16 method of stress-ng, and count the total bogo operations per second (in real time) based on wall clock run time.",
        framework="stress_ng",
        measurement="best1",
        unit="Bogo operations per second (ops/s)",
        note=_BENCHMARK_SINGLE_THREAD_NOTE,
    ),
    Benchmark(
        benchmark_id="stress_ng:bestn",
        name="stress-ng div16 multi-core",
        category="stress-ng",
        description="Stress the CPU with the div16 method of stress-ng using a varying number of vCPU cores, and count the measured maximum total bogo operations per second (in real time) based on wall clock run time.",
        framework="stress_ng",
        measurement="bestn",
        unit="Bogo operations per second (ops/s)",
    ),
    Benchmark(
        benchmark_id="static_web:rps",
        name="Static web server+client speed",
        category="Static web server",
        description="Serving smaller (1-64 KiB) and larger (256-512 KiB) files using a static HTTP server (binserve) as a single process, and benchmarking each workload (wrk) using variable number of threads (and keeping the threads with the maximum performance) and connections (recorded after divided by the number of vCPUs to make it comparable with other servers with different vCPU count) on the same server. The measured RPS is not the maximum expected server speed, as the server shares CPU with the client.",
        framework="static_web",
        measurement="rps",
        config_fields={
            "size": "Served file size (KiB).",
            "connections_per_vcpus": "Open HTTP connections per vCPU(s).",
        },
        unit="Requests per second (rps)",
        note=(
            "This benchmark does not scale well on large instances (100+ vCPUs) "
            "due to a listener bottleneck in the single-process HTTP server."
        ),
    ),
    Benchmark(
        benchmark_id="static_web:rps-extrapolated",
        name="Static web server (extrapolated) speed",
        category="Static web server",
        description="Serving smaller (1-64 KiB) and larger (256-512 KiB) files using a static HTTP server (binserve) as a single process, and benchmarking each workload (wrk) using variable number of threads (and keeping the threads with the maximum performance) and connections (recorded after divided by the number of vCPUs to make it comparable with other servers with different vCPU count) on the same server. The extrapolated RPS is based on the measured RPS adjusted by the server's and client's time spent executing in user/system mode, so trying to control for the client resource usage.",
        framework="static_web",
        measurement="rps-extrapolated",
        config_fields={
            "size": "Served file size (KiB).",
            "connections_per_vcpus": "Open HTTP connections per vCPU(s).",
        },
        unit="Requests per second (rps)",
        note=(
            "This benchmark does not scale well on large instances (100+ vCPUs) "
            "due to a listener bottleneck in the single-process HTTP server."
        ),
        source=ExtrapolatedSource(
            derived_from=["static_web:rps"],
            note=(
                "Measured RPS adjusted by server/client user+system CPU time "
                "to control for client resource usage"
            ),
        ),
    ),
    Benchmark(
        benchmark_id="static_web:throughput",
        name="Static web server+client throughput",
        category="Static web server",
        description="Serving smaller (1-64 KiB) and larger (256-512 KiB) files using a static HTTP server (binserve) as a single process, and benchmarking each workload (wrk) using variable number of threads (and keeping the threads with the maximum performance) and connections (recorded after divided by the number of vCPUs to make it comparable with other servers with different vCPU count) on the same server. Throughput is calculated by multiplying the RPS with the served file size. The measured RPS is not the maximum expected server speed, as the server shares CPU with the client.",
        framework="static_web",
        measurement="throughput",
        config_fields={
            "size": "Served file size (KiB).",
            "connections_per_vcpus": "Open HTTP connections per vCPU(s).",
        },
        unit="Bytes per second (Bps)",
        note=(
            "This benchmark does not scale well on large instances (100+ vCPUs) "
            "due to a listener bottleneck in the single-process HTTP server."
        ),
    ),
    Benchmark(
        benchmark_id="static_web:throughput-extrapolated",
        name="Static web server (extrapolated) throughput",
        category="Static web server",
        description="Serving smaller (1-64 KiB) and larger (256-512 KiB) files using a static HTTP server (binserve) as a single process, and benchmarking each workload (wrk) using variable number of threads (and keeping the threads with the maximum performance) and connections (recorded after divided by the number of vCPUs to make it comparable with other servers with different vCPU count) on the same server. Extrapolated throughput is calculated by multiplying the extrapolated RPS with the served file size. The extrapolated RPS is based on the measured RPS adjusted by the server's and client's time spent executing in user/system mode, so trying to control for the client resource usage.",
        framework="static_web",
        measurement="throughput-extrapolated",
        config_fields={
            "size": "Served file size (KiB).",
            "connections_per_vcpus": "Open HTTP connections per vCPU(s).",
        },
        unit="Bytes per second (Bps)",
        note=(
            "This benchmark does not scale well on large instances (100+ vCPUs) "
            "due to a listener bottleneck in the single-process HTTP server."
        ),
        source=ExtrapolatedSource(
            derived_from=["static_web:throughput"],
            note=(
                "Measured throughput adjusted by server/client user+system CPU time "
                "to control for client resource usage"
            ),
        ),
    ),
    Benchmark(
        benchmark_id="static_web:latency",
        name="Static web server latency",
        category="Static web server",
        description="Serving smaller (1-64 KiB) and larger (256-512 KiB) files using a static HTTP server (binserve) as a single process, and benchmarking each workload (wrk) using variable number of threads (and keeping the threads with the maximum performance) and connections (recorded after divided by the number of vCPUs to make it comparable with other servers with different vCPU count) on the same server. The average latency reported by wrk.",
        framework="static_web",
        measurement="latency",
        config_fields={
            "size": "Served file size (KiB).",
            "connections_per_vcpus": "Open HTTP connections per vCPU(s).",
        },
        unit="Seconds (sec)",
        higher_is_better=False,
        note=_benchmark_throughput_latency_note("static_web:rps"),
    ),
    Benchmark(
        benchmark_id="redis:rps",
        name="Redis server+client speed",
        category="Database",
        subcategory="Redis",
        description="Running a pair of redis server and benchmarking client (memtier_benchmark) on each vCPU to evaluate the performance of SET operations, using different number of concurrent pipelined requests. The measured RPS (ops/sec) is the sum of RPS measured in all parallel processes, but is not the maximum expected redis server speed, as the server(s) share CPU with the client(s).",
        framework="redis",
        measurement="rps",
        config_fields={
            "operation": "Type of operation, e.g. SET or GET a key.",
            "pipeline": "The number of concurrent pipelined requests.",
        },
        unit="Operations per second (ops/sec)",
    ),
    Benchmark(
        benchmark_id="redis:rps-extrapolated",
        name="Redis server (extrapolated) speed",
        category="Database",
        subcategory="Redis",
        description="Running a pair of redis server and benchmarking client (memtier_benchmark) on each vCPU to evaluate the performance of SET operations, using different number of concurrent pipelined requests. The extrapolated server speed is based on the measured speed adjusted by the server's and client's time spent executing in user/system mode, so trying to control for the client resource usage.",
        framework="redis",
        measurement="rps-extrapolated",
        config_fields={
            "operation": "Type of operation, e.g. SET or GET a key.",
            "pipeline": "The number of concurrent pipelined requests.",
        },
        unit="Operations per second (ops/sec)",
        source=ExtrapolatedSource(
            derived_from=["redis:rps"],
            note=(
                "Measured RPS adjusted by server/client user+system CPU time "
                "to control for client resource usage"
            ),
        ),
    ),
    Benchmark(
        benchmark_id="redis:latency",
        name="Redis latency",
        category="Database",
        subcategory="Redis",
        description="Running a pair of redis server and benchmarking client (memtier_benchmark) on each vCPU to evaluate the performance of SET operations, using different number of concurrent pipelined requests. The average latency reported by memtier_benchmark.",
        framework="redis",
        measurement="latency",
        config_fields={
            "operation": "Type of operation, e.g. SET or GET a key.",
            "pipeline": "The number of concurrent pipelined requests.",
        },
        unit="Milliseconds (ms)",
        higher_is_better=False,
        note=_benchmark_throughput_latency_note("redis:rps"),
    ),
    # https://www.cpubenchmark.net/cpu_test_info.html
    _passmark(
        name="CPU Mark",
        description="A composite average of the Integer, Floating point, Prime and String Sorting test scores, which can be used to compare CPUs from different platforms (even e.g. desktop vs mobile).",
        unit=None,
    ),
    _passmark(
        name="CPU Integer Maths Test",
        description="Testing how fast the CPU can perform mathematical integer operations, using large sets of an equal number of random 32-bit and 64-bit integers for addition, subtraction, multiplication and division, with integer buffers totaling about 240kb per core.",
        unit="Millions of operations per second (Mops/s)",
    ),
    _passmark(
        name="CPU Floating Point Maths Test",
        description="Testing how fast the CPU can perform mathematical floating point operations, using large sets of an equal number of random 32-bit and 64-bit floating point numbers for addition (30% of the time), subtraction (30% of the time), multiplication (30% of the time) and division (10% of the time), with floating point buffers totaling about 240kb per core.",
        unit="Millions of operations per second (Mops/s)",
    ),
    _passmark(
        name="CPU Prime Numbers Test",
        description="Finding prime numbers using the Sieve of Atkin formula (with a limit of 32 million) on 64-bit integers with 4MB of memory per thread.",
        unit="Million prime numbers per second (Mnums/s)",
    ),
    _passmark(
        name="CPU String Sorting Test",
        description="Sorting strings using the Quicksort algorithm with memory buffers totaling about 25MB per core.",
        unit="Thousands of strings per second (Kstrings/s)",
    ),
    _passmark(
        name="CPU Encryption Test",
        description="Encrypting blocks of random data using AES, SHA256 and ECDSA with any available specialized CPU instruction sets and memory buffers totaling about 1MB per core.",
        unit="Megabytes per second (MB/s)",
    ),
    _passmark(
        name="CPU Compression Test",
        description="Using Gzip (Crypto++ 8.6) to compress blocks of data with a 4MB memory buffer size per core.",
        unit="Kilobytes per second (kB/s)",
    ),
    _passmark(
        name="CPU Single Threaded Test",
        description="Using a single logical core for a mixture of floating point, string sorting and data compression tests.",
        unit="Millions of operations per second (Mops/s)",
        note=_BENCHMARK_SINGLE_THREAD_NOTE,
    ),
    _passmark(
        name="CPU Physics Test",
        description="Simulating the same physics interactions as many times as possible within a timeframe, using the Bullet Physics Engine (version 2.88 for x86, 3.07 for ARM).",
        unit="Frames per second (fps)",
    ),
    _passmark(
        name="CPU Extended Instructions Test",
        description="Testing how fast the CPU can perform mathematical operations using extended instructions, such as SSE, FMA, AVX, AVX512 and NEON.",
        unit="Millions of matrices per second (Mmat/s)",
    ),
    # https://forums.passmark.com/performancetest/4599-formula-cpu-mark-memory-mark-and-disk-mark?p=54964#post54964
    _passmark(
        name="Memory Mark",
        description="A composite score of PassMark's Database and Memory test cases",
        unit=None,
        note=_benchmark_plateau_note(16),
        subcategory="Memory",
    ),
    _passmark(
        name="Database Operations",
        # https://www.databasebenchmarks.net/chart-notes.html
        description="Single threaded and multi-threaded CRUD operations, such as INSERT (40%), SELECT (26%), UPDATE (24%), and DELETE (10%) on a relational database with 4 tables and 1k rows per table.",
        unit="Thousands of operations per second (Kops/s)",
        note=_benchmark_plateau_note(32),
        subcategory="Memory",
    ),
    # https://www.memorybenchmark.net/graph_notes.html
    _passmark(
        name="Memory Read Cached",
        description="Read a combination of 32-bit and 64-bit data from memory.",
        unit="Megabytes per second (MB/s)",
        note=_BENCHMARK_FAMILY_INDEPENDENT_NOTE,
        subcategory="Memory",
    ),
    _passmark(
        name="Memory Read Uncached",
        description="Read a combination of 32-bit and 64-bit data from memory using a 512 MB block size.",
        unit="Megabytes per second (MB/s)",
        note=_BENCHMARK_FAMILY_INDEPENDENT_NOTE,
        subcategory="Memory",
    ),
    _passmark(
        name="Memory Write",
        description="Write a combination of 32-bit and 64-bit data to the memory using a 512 MB block size.",
        unit="Megabytes per second (MB/s)",
        note=_BENCHMARK_FAMILY_INDEPENDENT_NOTE,
        subcategory="Memory",
    ),
    _passmark(
        name="Memory Latency",
        description="Measuring the time it takes for a single byte of memory to be transferred to the CPU for processing. A 512 MB buffer is allocated and then filled with pointers to other locations in the buffer, looping through a linked list.",
        unit="Nanoseconds (ns)",
        higher_is_better=False,
        note=_BENCHMARK_FAMILY_INDEPENDENT_NOTE,
        subcategory="Memory",
    ),
    Benchmark(
        benchmark_id="membench:bandwidth_read",
        name="Memory read bandwidth (sc-membench)",
        category="Memory bandwidth",
        subcategory="membench",
        description="Measures aggregate sequential read bandwidth across all threads using OpenMP parallelization.",
        framework="membench",
        measurement="memory_bandwidth",
        config_fields={
            "size_kb": "Per-thread buffer size in KiB.",
            "scope": "RAM: working set exceeds total CPU cache (L3, else L2, else L1d).",
        },
        unit="MB/s",
    ),
    Benchmark(
        benchmark_id="membench:bandwidth_write",
        name="Memory write bandwidth (sc-membench)",
        category="Memory bandwidth",
        subcategory="membench",
        description="Measures aggregate sequential write bandwidth across all threads using OpenMP parallelization.",
        framework="membench",
        measurement="memory_bandwidth",
        config_fields={
            "size_kb": "Per-thread buffer size in KiB.",
            "scope": "RAM: working set exceeds total CPU cache (L3, else L2, else L1d).",
        },
        unit="MB/s",
    ),
    Benchmark(
        benchmark_id="membench:bandwidth_copy",
        name="Memory copy bandwidth (sc-membench)",
        category="Memory bandwidth",
        subcategory="membench",
        description="Measures aggregate memory copy bandwidth across all threads using OpenMP parallelization.",
        framework="membench",
        measurement="memory_bandwidth",
        config_fields={
            "size_kb": "Per-thread buffer size in KiB.",
            "scope": "RAM: working set exceeds total CPU cache (L3, else L2, else L1d).",
        },
        unit="MB/s",
    ),
    Benchmark(
        benchmark_id="membench:latency",
        name="Memory latency (sc-membench)",
        category="Memory latency",
        subcategory="membench",
        description="Measures median memory latency using pointer chasing with randomized access to defeat hardware prefetching.",
        framework="membench",
        measurement="memory_latency",
        config_fields={
            "size_kb": "Per-thread buffer size in KiB.",
            "scope": "RAM: working set exceeds total CPU cache (L3, else L2, else L1d).",
        },
        unit="ns",
        higher_is_better=False,
    ),
    Benchmark(
        benchmark_id="llm_speed:text_generation",
        name="LLM inference speed for text generation",
        category="LLM inference speed",
        subcategory="Text generation",
        description="Running llama-bench from llama.cpp using various quantized model files to measure the speed of generating 16 to 4k tokens.",
        framework="llm_speed",
        measurement="text_generation",
        config_fields={
            "model": "Name of the model file used.",
            "tokens": "Number of tokens processed in one run.",
        },
        unit="tokens/second (t/s)",
        note=_BENCHMARK_LLM_SPEED_NOTE,
    ),
    Benchmark(
        benchmark_id="llm_speed:prompt_processing",
        name="LLM inference speed for prompt processing",
        category="LLM inference speed",
        subcategory="Prompt processing",
        description="Running llama-bench from llama.cpp using various quantized model files to measure the speed of processing 16 to 16k tokens.",
        framework="llm_speed",
        measurement="prompt_processing",
        config_fields={
            "model": "Name of the model file used.",
            "tokens": "Number of tokens processed in one run.",
        },
        unit="tokens/second (t/s)",
        note=_BENCHMARK_LLM_SPEED_NOTE,
    ),
    Benchmark(
        benchmark_id="nvbandwidth:all:host_to_gpu",
        name="Node host-to-GPU bandwidth (nvbandwidth)",
        category="GPU bandwidth",
        subcategory="Node (all GPUs)",
        description="Total node ingest rate (GB/s) when CPU streams to ALL GPUs concurrently utilizing CE (Copy Engine).",
        framework="nvbandwidth",
        measurement="gpu_bandwidth",
        unit="GB/s",
    ),
    Benchmark(
        benchmark_id="nvbandwidth:all:gpu_to_host",
        name="Node GPU-to-host bandwidth (nvbandwidth)",
        category="GPU bandwidth",
        subcategory="Node (all GPUs)",
        description="Total node egress rate (GB/s) when ALL GPUs stream to CPU concurrently utilizing CE (Copy Engine).",
        framework="nvbandwidth",
        measurement="gpu_bandwidth",
        unit="GB/s",
    ),
    Benchmark(
        benchmark_id="nvbandwidth:all:duplex",
        name="Node baseline directional bandwidth (nvbandwidth)",
        category="GPU bandwidth",
        subcategory="Node (all GPUs)",
        description="Conservative per-direction bandwidth (GB/s) under simultaneous bi-directional saturation utilizing CE (Copy Engine).",
        framework="nvbandwidth",
        measurement="gpu_bandwidth",
        unit="GB/s",
    ),
    Benchmark(
        benchmark_id="nvbandwidth:slot:host_to_gpu",
        name="Per-GPU host-to-GPU bandwidth (nvbandwidth)",
        category="GPU bandwidth",
        subcategory="Single GPU slot",
        description="Average physical PCIe slot ingest speed (GB/s) per single GPU utilizing CE (Copy Engine).",
        framework="nvbandwidth",
        measurement="gpu_bandwidth",
        unit="GB/s",
    ),
    Benchmark(
        benchmark_id="nvbandwidth:slot:gpu_to_host",
        name="Per-GPU GPU-to-host bandwidth (nvbandwidth)",
        category="GPU bandwidth",
        subcategory="Single GPU slot",
        description="Average physical PCIe slot egress speed (GB/s) per single GPU utilizing CE (Copy Engine).",
        framework="nvbandwidth",
        measurement="gpu_bandwidth",
        unit="GB/s",
    ),
    Benchmark(
        benchmark_id="nvbandwidth:slot:latency",
        name="Per-GPU host-device latency (nvbandwidth)",
        category="GPU latency",
        subcategory="Single GPU slot",
        description="Average round-trip transit time (ns) between CPU and individual GPUs utilizing SM (Streaming Multiprocessor).",
        framework="nvbandwidth",
        measurement="gpu_latency",
        unit="ns",
        higher_is_better=False,
    ),
    Benchmark(
        benchmark_id="nvbandwidth:p2p:single",
        name="GPU-to-GPU P2P bandwidth (nvbandwidth)",
        category="GPU bandwidth",
        subcategory="Peer-to-peer",
        description="Single NVLink/P2P lane write speed (GB/s) between any two GPUs utilizing CE (Copy Engine).",
        framework="nvbandwidth",
        measurement="gpu_bandwidth",
        unit="GB/s",
    ),
    Benchmark(
        benchmark_id="nvbandwidth:p2p:duplex",
        name="GPU-to-GPU P2P duplex bandwidth (nvbandwidth)",
        category="GPU bandwidth",
        subcategory="Peer-to-peer",
        description="Full-duplex NVLink/P2P lane speed (GB/s) during simultaneous dual-GPU transfers utilizing CE (Copy Engine).",
        framework="nvbandwidth",
        measurement="gpu_bandwidth",
        unit="GB/s",
    ),
    Benchmark(
        benchmark_id="nvbandwidth:p2p:latency",
        name="GPU-to-GPU P2P latency (nvbandwidth)",
        category="GPU latency",
        subcategory="Peer-to-peer",
        description="Direct transit latency (ns) between GPU pairs over NVLink/P2P utilizing SM (Streaming Multiprocessor).",
        framework="nvbandwidth",
        measurement="gpu_latency",
        unit="ns",
        higher_is_better=False,
    ),
    Benchmark(
        benchmark_id="nvbandwidth:p2p:gather",
        name="GPU-to-GPU P2P gather bandwidth (nvbandwidth)",
        category="GPU bandwidth",
        subcategory="Peer-to-peer",
        description="Intake bandwidth (GB/s) on a single target GPU when all peer GPUs send to it at once utilizing CE (Copy Engine).",
        framework="nvbandwidth",
        measurement="gpu_bandwidth",
        unit="GB/s",
    ),
    Benchmark(
        benchmark_id="nvbandwidth:efficiency:sm_ce_ratio",
        name="SM/CE copy efficiency (nvbandwidth)",
        category="GPU bandwidth",
        subcategory="Efficiency",
        description="Ratio (between 0.0 and 1.0) showing compute-core copy efficiency vs. raw DMA Copy Engine capacity, or in other terms, the ratio between CE (Copy Engine) and Streaming Multiprocessor (SM).",
        framework="nvbandwidth",
        measurement="gpu_efficiency",
        unit="ratio",
    ),
    Benchmark(
        benchmark_id="pgbench:heavy_read_only",
        name="PostgreSQL heavy read-only throughput",
        category="Database",
        subcategory="PostgreSQL",
        description=(
            "Measures PostgreSQL throughput with a remote pgbench client against "
            "a custom, cache-resident, read-only transaction (joins, aggregates, "
            "full-text search, arrays, regex, TOAST) that fits in shared_buffers, so "
            "the score reflects engine CPU and memory behavior rather than disk or "
            "network. Server and client run in the same availability zone. Servers "
            "use pgtune-style host GUCs, while DBaaS keep the vendor-managed config. "
            "Each score is TPM at a given client concurrency; the typical profile is "
            "1, vCPUs/2, vCPUs, and 2*vCPUs (additional points may be present). This "
            "is a synthetic proxy for relative RDBMS performance across server types, "
            "not a prediction of any specific application's throughput."
        ),
        framework="pgbench",
        measurement="heavy_read_only",
        source={"kind": "measured"},
        config_fields={
            "concurrency": (
                "Parallel client query count (integer). Typical profile: 1, "
                "vCPUs/2, vCPUs, and 2*vCPUs (may include additional points)."
            )
        },
        unit="Transactions per minute (TPM)",
    ),
    Benchmark(
        benchmark_id="pgbench:heavy_read_only:single",
        name="PostgreSQL heavy read-only baseline (single connection)",
        category="Database",
        subcategory="PostgreSQL",
        description=(
            "Baseline PostgreSQL throughput with a single remote pgbench client "
            "connection against a custom, cache-resident, read-only transaction "
            "(joins, aggregates, full-text search, arrays, regex, TOAST) that fits "
            "in shared_buffers. Server and client run in the same availability zone. "
            "Servers use pgtune-style host GUCs, while DBaaS keep the vendor-managed "
            "config. Useful for comparing per-session engine and CPU efficiency "
            "across server types and sizes, because the score does not necessarily scale with "
            "extra vCPUs the way peak throughput does. This is a synthetic proxy for "
            "relative RDBMS performance, not a prediction of any specific "
            "application's throughput."
        ),
        framework="pgbench",
        measurement="heavy_read_only:single",
        source={"kind": "measured"},
        unit="Transactions per minute (TPM)",
        note=_BENCHMARK_SINGLE_SESSION_NOTE,
    ),
    Benchmark(
        benchmark_id="pgbench:heavy_read_only:peak",
        name="PostgreSQL heavy read-only peak throughput",
        category="Database",
        subcategory="PostgreSQL",
        description=(
            "Maximum PostgreSQL throughput over the pgbench concurrency profile "
            "(typically 1, vCPUs/2, vCPUs, and 2*vCPUs) with a remote client against "
            "a custom, cache-resident, read-only transaction (joins, aggregates, "
            "full-text search, arrays, regex, TOAST) that fits in shared_buffers. "
            "Server and client run in the same availability zone. Servers use "
            "pgtune-style host GUCs, while DBaaS keep the vendor-managed config. "
            "This is a synthetic proxy for relative RDBMS performance across server "
            "types, not a prediction of any specific application's throughput."
        ),
        framework="pgbench",
        measurement="heavy_read_only:peak",
        source={"kind": "measured"},
        environment_fields={
            "peak_concurrency": "Client concurrency at which the peak throughput was measured.",
        },
        unit="Transactions per minute (TPM)",
    ),
]

benchmarks.extend(
    _stress_ng_benchmark(method, subcategory, description)
    for method, subcategory, description in _STRESS_NG_METHODS
)

# document the keys recorded in BenchmarkScore.environment
_ENVIRONMENT_FIELDS = {
    "kernel_version": "Linux kernel version of the server running the benchmark (not recorded for managed databases).",
    "measured_at": "Timestamp (UTC) of finishing the benchmark run.",
}
_FRAMEWORK_ENVIRONMENT_FIELDS = {
    "nvbandwidth": {
        "driver_version": "NVIDIA driver version.",
        "cuda_runtime_version": "CUDA runtime version.",
        "nvbandwidth_version": "Version of the nvbandwidth tool.",
        "gpu_count": "Number of GPUs seen by nvbandwidth.",
        "p2p_supported": "Whether peer-to-peer (device-to-device) GPU transfers were supported.",
    },
    "pgbench": {
        "database_engine_version": "PostgreSQL server version.",
        "latency_avg_ms": "Average transaction latency (ms).",
    },
}
for benchmark in benchmarks:
    benchmark.environment_fields = {
        **_ENVIRONMENT_FIELDS,
        **_FRAMEWORK_ENVIRONMENT_FIELDS.get(benchmark.framework, {}),
        **benchmark.environment_fields,
    }

# dynamically add synthetic compound/augmented workloads
for workload_name, workload in WORKLOADS.items():
    benchmarks.append(
        Benchmark(
            benchmark_id=f"workload_profile:{workload_name}",
            name=f"Workload profile: {workload.name}",
            category="Workload profile",
            description=(
                f"Precomputed compound score for {workload.name} workloads. "
                "A weighted average (geometric mean) of benchmark scores compared to "
                "their medians: score = ∏ (x_i / m_i)^(w_i / Σw). "
                "The score of 1.0 represents a synthetic baseline server with the median "
                "performance of each component benchmark; 0.5 means roughly half the "
                "performance; and 2.0 means twice the performance of that reference "
                "profile. "
                "Component weights: "
                + ", ".join(
                    [
                        f"{int(benchmark.weight * 100)}% {benchmark.label}"
                        for benchmark in workload.benchmarks
                    ]
                )
                + ". Rationale for component selection: "
                + workload.rationale
            ),
            framework="workload_profile",
            measurement="score",
            source=CompoundSource(
                aggregation=BenchmarkComponentAggregationMethod.WEIGHTED_GEOMETRIC_MEAN,
                normalization=BenchmarkComponentNormalizationMethod.MEDIAN_RATIO,
                components=list(workload.benchmarks),
                impact_formula=_impact_tooltip(
                    BenchmarkComponentAggregationMethod.WEIGHTED_GEOMETRIC_MEAN,
                    BenchmarkComponentNormalizationMethod.MEDIAN_RATIO,
                ),
            ),
        )
    )
