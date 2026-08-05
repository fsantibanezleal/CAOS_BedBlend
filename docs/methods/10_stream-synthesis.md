# Method 10: stream synthesis from a dig sequence

Source read for this document: `bedblend/stream.py`, with `Payload` from `bedblend/truck.py` and
`TruckSpec` from `bedblend/terrain.py`. Gates: `tests/test_blending.py`, `tests/test_topography.py`.
Every number below was produced by running the installed package.

This module produces the ordered sequence of truckloads that arrives at the stockpile. It is short,
it has no dependencies, and it encodes one correction that changes what the whole package is able to
claim.

---

## 1. The correction: autocorrelation is an output, not an input

The previous version of this engine took `range_t`, the practical range of the grade covariance in
tonnes, as an INPUT PARAMETER. The module header calls that backwards, and it is. The autocorrelation
of material arriving at a stockpile is not a property anyone sets. It is a consequence of how the pit
is being dug. The header quotes the mechanism directly:

> "When data are collected from a single grade block, the material transported to dump locations are
> spatially correlated."

Consecutive trucks load from the same dig block, so consecutive loads carry similar grades, and the
correlation length of the stream is set by how long a shovel dwells in one block before it moves. The
industrial simulation the module cites models it exactly this way: the deposit is mined sequentially
by pushback and by pit, top bench first and then one bench down, with two adjacent blocks loaded into
each truck (Neufeld, Lyall and Deutsch, CCG Report 8 paper 306, 2006).

So this module takes what an operation actually controls, the block layout and the shovel schedule,
and lets the correlation fall out. `measured_range_t` then REPORTS the range the generated stream
actually has. That is the honest direction of the relationship, and it is what makes the causal story
checkable: change the dwell, watch the range move, watch the variance reduction move with it.

The causal claim is gated rather than asserted in prose. `tests/test_blending.py::
test_a_shorter_shovel_dwell_decorrelates_the_stream_faster` changes only `loads_per_block` (5 against
60, everything else fixed at 800 loads and seed 9) and asserts that the measured range follows.
Running it: dwell 5 gives 1098 t, dwell 60 gives 13 865 t. See section 6 for a caveat about that
second number.

---

## 2. The generator (`Xorshift`)

Everything stochastic in this module comes from one seeded 32-bit xorshift, written out explicitly
rather than using `random` or numpy. The reason is in the class docstring and it is a hard
requirement, not a style choice: a browser implementation of the same engine has to produce the
identical sequence bit for bit, and a language's built-in generator is not a portable contract.

```
state_0 = (seed | 1) & 0xFFFFFFFF          the OR forces a non-zero state

x ^= (x << 13) & 0xFFFFFFFF
x ^= (x >> 17)
x ^= (x << 5)  & 0xFFFFFFFF

uniform() = state / 0x100000000            0x100000000 = 2^32
normal()  = Box-Muller over two uniforms, caching the sine deviate so both are used
```

`normal()` draws `u1 = max(uniform(), 1e-12)` and `u2 = uniform()`, returns
`sqrt(-2 ln u1) * cos(2 pi u2)`, and stores `sqrt(-2 ln u1) * sin(2 pi u2)` in `_spare` for the next
call. Every second call therefore consumes no uniforms. That matters if you are trying to reproduce
the stream in another language: the spare must be replicated too.

Verified moments over 200 000 draws per seed, where the standard error of the mean is 0.00224:

```
seed      1     mean  0.00106     sd 1.00002
seed      5     mean  0.00133     sd 0.99917
seed      9     mean -0.00248     sd 1.00047
seed  12345     mean  0.00218     sd 0.99999
```

The generator is not biased. This is worth recording because a short sequence looks as though it is:
seeds 1 through 6 at 600 loads and a dwell of 25 all produced a realised mean grade above the nominal
0.62 (0.67464, 0.66915, 0.66915, 0.68667, 0.68667, 0.64972). That is a small-sample effect, not a
generator defect, and section 7 quantifies it.

**`seed | 1` means an even seed and the odd seed above it are the SAME generator.** Look at the
repeats in that list. `Xorshift(2)` and `Xorshift(3)` both start at state 3 and emit an identical
sequence, verified by comparing draws; so do 0 and 1, 4 and 5, and every pair after. Only odd seeds
address distinct streams, so a sweep over `range(1, 61)` explores 31 distinct generators and not 60,
and a "seed" reported in an artifact is not a unique identifier of the stream it produced. The
non-zero-state guard is necessary (xorshift is stuck at zero forever), but `(seed * 2) | 1` or a
rejection of the zero state would have kept the seed space injective.

---

## 3. `DigBlock` and `DigSequence`

```python
@dataclass(frozen=True)
class DigBlock:
    index: int          # position in the dig order, 0-based; this is what Payload.source_block carries
    grade: float        # the block's grade, drawn once (unit not declared by the code, see below)
    n_loads: int        # how many truckloads come out of this block
    bench: int = 0      # which bench the block sits on

@dataclass(frozen=True)
class DigSequence:
    blocks: list[DigBlock]

    @property
    def n_loads(self) -> int:      # sum of every block's n_loads
```

A block grade is drawn once and every load from that block sits near it. That is the entire
correlation mechanism: the block is the correlated unit, and the shovel's dwell in it is the
correlation length expressed in tonnes. `blocks` are consumed in ORDER by `payloads_from`, so
reordering them changes the stream's structure without changing a single grade. The sequence IS the
control.

**The freeze is shallow.** Both dataclasses declare `frozen=True`, so `seq.blocks = [...]` raises
`FrozenInstanceError`, but `blocks` is a plain list and `seq.blocks.append(...)` succeeds and changes
`seq.n_loads`. Verified. Treat a `DigSequence` as immutable by convention, not by enforcement.

**The code declares no unit for grade.** Nothing in `stream.py`, `truck.py` or `blocks.py` states
whether a grade is a percentage, a fraction or grams per tonne. It is carried as a dimensionless
float from end to end and the metrics in `blending.py` are ratios, so the unit cancels. The defaults
(a mean of 0.62 with a between-block standard deviation of 0.16) are consistent with a percent-copper
figure, but the source does not say so and neither will this document.

---

## 4. `dig_sequence`: building the schedule

```python
dig_sequence(
    *,
    n_loads: int,
    seed: int,
    loads_per_block: int = 20,
    mean_grade: float = 0.62,
    block_sd: float = 0.16,
    bench_trend: float = 0.0,
    n_benches: int = 1,
) -> DigSequence
```

All arguments are keyword-only. The two required ones have no defaults.

| Parameter | Default | Unit | What it is |
|---|---|---|---|
| `n_loads` | required | truckloads (count) | Total loads the sequence must supply. |
| `seed` | required | integer | Seeds the `Xorshift` that draws the block grades. |
| `loads_per_block` | 20 | truckloads per block (count) | THE SHOVEL DWELL. At the 231 t default truck this is 4620 t per block. |
| `mean_grade` | 0.62 | grade units (undeclared) | Centre of the block-grade distribution. |
| `block_sd` | 0.16 | grade units (undeclared) | Standard deviation BETWEEN blocks. |
| `bench_trend` | 0.0 | grade units per bench index | Linear grade drift added as `bench_trend * bench`. |
| `n_benches` | 1 | count, but see below | Multiplier in the bench-index formula. |

The body, transcribed:

```
n_blocks = max(1, ceil(n_loads / max(1, loads_per_block)))

for each block k, while loads remain:
    take  = min(loads_per_block, n_loads - placed)
    bench = (k * n_benches) // n_blocks
    grade = mean_grade + block_sd * normal() + bench_trend * bench
    emit DigBlock(index=k, grade=max(grade, 0.0), n_loads=take, bench=bench)
```

`loads_per_block` is the parameter that sets the stream's correlation length, and the docstring is
explicit about the operational meaning: a short dwell means the stream decorrelates quickly and the
pile has independent material to average; a long dwell means whole layers share a grade and the bed
can barely help. That is the honest version of what the old `range_t` knob was pretending to be.

The last block is short when `loads_per_block` does not divide `n_loads`. Verified with
`n_loads=100, loads_per_block=30`: four blocks of 30, 30, 30, 10.

### Where `dig_sequence` fails

**`loads_per_block=0` hangs forever.** The `max(1, ...)` guard protects the `n_blocks` computation
but NOT the loop body, where `take = min(loads_per_block, n_loads - placed)` evaluates to zero and
`placed` never advances. Verified: the call does not return within 8 seconds and has to be killed. A
negative value behaves the same way. There is no validation and no test covering it. The fix, when
someone gets to it, is a `max(1, loads_per_block)` on `take` or an explicit `ValueError`, and it
belongs with a test that asserts the raise.

**`n_benches` is a multiplier, not a bench count.** The formula `(k * n_benches) // n_blocks` gives
one bench per equal share of the block list only while `n_benches <= n_blocks`. Verified with four
blocks: `n_benches=4` produces benches 0, 1, 2, 3 as expected, but `n_benches=9` produces benches
0, 2, 4, 6. Values are skipped and the top bench, 8, is never reached. If you rely on the bench index
for anything beyond `bench_trend`, keep `n_benches` at or below the block count.

**The grade clamp biases the mean when `block_sd` is large relative to `mean_grade`.** The block
grade is `max(grade, 0.0)`, which is correct (a negative grade is not a thing) and silent. At the
defaults the clamp sits 3.875 standard deviations below the mean and effectively never fires. Push
the parameters and it does: with `mean_grade=0.05, block_sd=0.5, loads_per_block=5` over 40 loads at
seed 4, three of the eight block grades came back as exactly 0.0, and at seed 8 four of eight did. If
you see a spike of zeros in a grade histogram, this is where it came from.

---

## 5. `payloads_from`: the schedule becomes a stream

```python
payloads_from(
    seq: DigSequence,
    *,
    seed: int,
    tonnes_per_truck: float = 231.0,
    truck_spread: float = 0.06,
    within_block_sd: float = 0.02,
    grade_uncertainty: float = 0.12,
) -> list[Payload]
```

| Parameter | Default | Unit | What it is |
|---|---|---|---|
| `seq` | required | `DigSequence` | Consumed in block order; block order is dig order. |
| `seed` | required | integer | Seeds a SECOND generator, `Xorshift(seed ^ 0x5EED)`. |
| `tonnes_per_truck` | 231.0 | tonnes | Nominal payload. Traces to `TruckSpec.payload_t`, the CAT 793F. |
| `truck_spread` | 0.06 | dimensionless, relative | Multiplicative load-to-load payload variation. |
| `within_block_sd` | 0.02 | grade units (undeclared) | Residual grade variation INSIDE one block. |
| `grade_uncertainty` | 0.12 | dimensionless, relative | Ore-control misclassification carried on every load. |

Per load, in this evaluation order (Python evaluates the keyword arguments left to right, and the
order matters for reproducing the stream elsewhere):

```
tonnes = tonnes_per_truck * (1.0 + truck_spread * normal())        drawn FIRST
grade  = max(block.grade + within_block_sd * normal(), 0.0)        drawn SECOND
Payload(tonnes, grade, source_block=block.index, grade_uncertainty=grade_uncertainty)
```

`Xorshift(seed ^ 0x5EED)` XORs the seed with 24 301, so passing the same integer to `dig_sequence`
and `payloads_from` (which the tests and the README both do) does not reuse the same random stream.
It is a decorrelating constant, nothing more.

**`within_block_sd` is small by construction and that is the point.** A block is the unit the
ore-control model calls uniform. If loads inside one block varied as much as loads between blocks
there would be no correlation to speak of, and the whole mechanism would collapse. At the defaults
the ratio is 0.02 against 0.16, a factor of eight. Its visible effect is on the nugget of the fitted
variogram: holding everything else fixed at 800 loads, seed 21, dwell 20, and fitting at
`n_lags=30`, a `within_block_sd` of 0.0 gives a fitted nugget of 0.003047, 0.02 gives 0.003492, and
0.10 gives 0.005805. Carry the `n_lags` with those numbers. `experimental_variogram` defaults to 20
lags, not 30, and the same sweep at the default reads 0.003621, 0.004092 and 0.004442: the same
ordering, different values. `docs/methods/09_blending-metrics.md` section 6 covers why the nugget
from `fit_spherical` moves with the binning.

**`grade_uncertainty` is a published number, carried rather than applied.** Ore-control
misclassification from sampling error alone runs 5 to 20 percent for base and precious metal mines,
with a further 9 to 19 percent ore loss from blast movement and dilution (Young and Rogers, Minerals
2021, 11, 636, section 1.6). The default of 0.12 is described in the docstring as the middle of the
5 to 20 percent band; the exact midpoint is 12.5 percent, so 0.12 is the band's middle rounded down.
Note what it does and does not do: it is ATTACHED to every load as metadata and propagated through
the ledger and into `Cut.grade_uncertainty`, but it is NOT used to perturb the grade. The grade a
load carries is the block grade plus within-block noise, and the uncertainty rides alongside it as a
declared error bar. A model that presented a crisp grade per load would be hiding a known error
rather than reporting one; this one reports it and leaves it to the consumer to render.

Also note that `Payload.grade_uncertainty` defaults to `0.0` on the dataclass in `truck.py`. The
0.12 comes from `payloads_from`, so a `Payload` constructed by hand carries no uncertainty at all
unless the caller supplies it.

**Payload tonnage is not clamped.** Grade is clamped at zero in two places; tonnes are not. At the
default spread of 0.06 a negative payload needs a 16.7-sigma draw, so it will not happen, but the
asymmetry is deliberate to note rather than to rely on. Measured over 5000 loads at seed 31: mean
231.223 t, standard deviation 13.753 t, coefficient of variation 0.0595 against the nominal 0.06, and
a range of 175.89 t to 280.24 t.

The 231 t default traces to `TruckSpec`, whose docstring attributes it to the CAT 793F measured in
the companion dumping study (Young and Rogers, Mining 2022,
[doi:10.3390/mining2010006](https://doi.org/10.3390/mining2010006)). One inconsistency inside this
repository, flagged rather than resolved: `bedblend/terrain.py` gives the page range as 86-102 and
the README gives 92-114 for the same DOI. The DOI is the reliable half of that citation.

---

## 6. `measured_range_t`: reporting what was generated

```python
measured_range_t(payloads: list[Payload], *, n_lags: int = 30) -> float
```

The practical range of the stream that was actually generated, in tonnes. This is the number the old
engine took as an input, and estimating it from the stream is what closes the loop.

```
mean   = (1/n) * sum_i g_i
var    = (1/n) * sum_i (g_i - mean)^2                         population variance of the grade series
t_per  = (1/n) * sum_i tonnes_i                               mean tonnes per load

for lag L = 1 .. min(n_lags, n // 2):
    gamma(L) = ( 1 / (2 * (n - L)) ) * sum_{i=0}^{n-L-1} (g_i - g_{i+L})^2
    if gamma(L) >= 0.95 * var:
        interpolate linearly between (L-1, gamma(L-1)) and (L, gamma(L))
        return the interpolated lag * t_per

return min(n_lags, n // 2) * t_per                            THE CENSORING CAP

    g_i    the grade of load i
    L      lag in LOADS, converted to tonnes at the end by multiplying by t_per
```

Three properties of that definition that are easy to get wrong when reading the output.

**It lags by load count, not by tonnage.** Unlike `blending.experimental_variogram`, which takes
cumulative tonnage as its position axis, this function computes a lag-index semivariogram over the
grade series and converts to tonnes at the very end by multiplying by the MEAN load. So it is a
count-based estimate wearing tonnage units. With a 6 percent payload spread the two agree closely; on
a fleet with genuinely mixed truck sizes they would not.

**It is not tonnage-weighted.** The variance and the semivariogram both treat every load equally.
This is the one place in the package where a grade statistic is computed on a count base, and it is
defensible here because the quantity being estimated is a correlation length rather than a dispersion
that has to be compared against another dispersion.

**It censors silently.** If the semivariogram never reaches 95 percent of the series variance within
the lag window, the function returns `max_lag * t_per`, the largest lag it looked at, with no flag.
A censored value is indistinguishable from a measured one. Verified on 800 loads, seed 9, dwell 60:

```
n_lags =  10   ->  2310.8 t     cap  2310.8 t     AT THE CAP
n_lags =  30   ->  6932.5 t     cap  6932.5 t     AT THE CAP
n_lags =  60   -> 13865.1 t     cap 13865.1 t     AT THE CAP
n_lags = 120   -> 22556.1 t     cap 27730.1 t     genuinely measured
```

The true practical range of that stream is about 22 556 t. At the default `n_lags=30` the function
reports 6932 t, less than a third of it, and looks like a measurement. This also touches the causal
test: `test_a_shorter_shovel_dwell_decorrelates_the_stream_faster` calls it at `n_lags=60` and the
long-dwell arm returns exactly the cap. The test's conclusion holds (a short dwell does decorrelate
faster, and the short arm at 1098 t is well inside the window), but the specific long value it
compares against is a floor on the true range, not the range.

Raise `n_lags` until the returned value stops equalling `min(n_lags, n // 2) * t_per`. That check is
two lines and there is no helper for it.

**It tracks the dwell when it is not censored.** Three streams of 1000 loads at seed 13, called with
`n_lags=200`, against the dwell converted to tonnes at 231 t per load:

```
dwell  5 loads =  1155 t   ->  measured  1082 t
dwell 20 loads =  4620 t   ->  measured  4430 t
dwell 50 loads = 11550 t   ->  measured 10976 t
```

Guards: fewer than 4 payloads returns 0.0, and a series with zero variance (every load the same
grade) returns 0.0 rather than the cap. Both verified.

---

## 7. `cumulative_tonnes`

```python
cumulative_tonnes(payloads: list[Payload]) -> list[float]
```

Running tonnage, which is the natural x-axis for anything plotted along the stream and the required
`positions` argument for `blending.experimental_variogram`. Note that the running total is appended
AFTER adding each load, so `out[0]` is the tonnage of the first load and not zero. On a 600-load
stream the first three entries were 223.08, 449.47 and 665.16 t and the last was 138 564.94 t. The
consequence for the variogram is minor but real: its `span` is `positions[-1] - positions[0]`, which
excludes the first load, so the default `max_lag = span / 3` is computed on 138 342 t rather than on
138 565 t.

An empty input returns an empty list. The output is non-decreasing for any non-negative tonnages,
which is exactly the precondition `experimental_variogram` needs and does not check.

### On the realised mean of a short sequence

A stream's realised mean grade is not `mean_grade`. It is the mean of `n_blocks` draws, so its
standard error is `block_sd / sqrt(n_blocks)`. At 600 loads with a dwell of 25 there are only 24
independent draws, giving a standard error of 0.0327 on a nominal 0.62. Measured over
`dig_sequence(n_loads=600, seed=s, loads_per_block=25)` for `s` in `range(1, 61)`, the mean of the
realised block-grade means was 0.62744 with a population spread across seeds of 0.03973, which sits
where the standard error predicts. Read that spread as an order of magnitude and not as a clean
sampling experiment: by the `seed | 1` collapse in section 2 those 60 seeds are only 31 distinct
generators, most of them counted twice.

The distribution itself is clean when you actually draw from it.
`dig_sequence(n_loads=200_000, seed=5, loads_per_block=1)` gives 200 000 block grades with a mean of
0.62021 and a standard deviation of 0.15986, against the nominal 0.62 and 0.16.

So a run of seeds that all come out high is noise, and a consuming product that displays "mean
grade 0.75" for a stream configured at 0.62 is not necessarily broken. What it should not do is
report the configured value as if it were the realised one.

---

## 8. Why this module decides whether the `1/N` bound is reachable

`blending.vrr_ideal(N) = 1 / N` assumes the `N` layers a reclaim cut crosses are INDEPENDENT draws
from the input distribution. Layers only average if they are independent. If the shovel dwelt in one
block long enough to build several layers, those layers carry nearly the same grade, averaging them
removes nothing, and the achieved VRR sits far above the bound no matter how well the pile was built.
The gap between achieved and ideal, which `blending.blending_efficiency` reports, is therefore in
large part a property of the DIG SEQUENCE and not of the stockpile at all. That is the reason this
module exists in the form it does.

The effect is large and it is measurable without a pile. The following isolates it: build a stream at
a given dwell, average consecutive groups of 25 loads (a crude stand-in for a layer that a cut
crosses), and compare the resulting VRR against the `1/25 = 0.04` bound.

```python
from bedblend.blending import blending_efficiency, mixing_effect, tonnage_weighted_variance, vrr
from bedblend.stream import dig_sequence, payloads_from

def layer_vrr(dwell, layer_len=25, n_loads=1200, seed=3):
    p = payloads_from(dig_sequence(n_loads=n_loads, seed=seed, loads_per_block=dwell), seed=seed)
    v_in = tonnage_weighted_variance([x.grade for x in p], [x.tonnes for x in p])
    g, w = [], []
    for i in range(0, len(p) - layer_len + 1, layer_len):
        chunk = p[i:i + layer_len]
        t = sum(x.tonnes for x in chunk)
        g.append(sum(x.grade * x.tonnes for x in chunk) / t)
        w.append(t)
    v_out = tonnage_weighted_variance(g, w)
    return vrr(v_in, v_out), blending_efficiency(vrr(v_in, v_out), layer_len), mixing_effect(v_in, v_out)
```

Measured:

```
dwell   1 load    ->  VRR 0.0301   efficiency 1.000 (capped)   E 5.762
dwell   5 loads   ->  VRR 0.2109   efficiency 0.190            E 2.178
dwell  25 loads   ->  VRR 0.9900   efficiency 0.040            E 1.005
dwell 100 loads   ->  VRR 0.9900   efficiency 0.040            E 1.005
```

At a dwell of one load every load is its own block, the 25 loads in a layer are independent, and the
result reaches the `1/25` bound and slightly beats it on this realisation, which is why
`blending_efficiency` caps at 1.0. At a dwell of 25 the layer is exactly one block: it averages 25
loads that all share a grade, removes one percent of the variance, and the mixing effect is 1.005,
which is to say nothing happened. A dwell of 100 is no worse, because the damage is already complete
once the dwell reaches the layer length.

This is a synthetic demonstration, not the engine's own pipeline. There is no terrain, no truck
routing, no dozer and no reclaim in it. Its purpose is to isolate the one variable, and what it shows
is that the dwell alone can move the achieved VRR from 0.03 to 0.99 with the layer count held
constant. Any recommendation layer that reports a poor VRR as a stacking problem, without looking at
the incoming range, is capable of being confidently wrong.

The `1/N` bound is derived and labelled as derived in `bedblend/blending.py`, and the De Wet (1994)
design equation that the literature normally cites for it is deliberately not reproduced anywhere in
this package because it could not be verified. See `docs/methods/09_blending-metrics.md` section 4.

---

## 9. What this module is, and what it is not

It IS a generator of a correlated grade and tonnage stream whose correlation structure is produced by
a block layout and a shovel schedule, reproducible bit for bit from `(parameters, seed)`, with the
resulting correlation length reported rather than assumed.

It is NOT a geostatistical simulation of a deposit. There is no spatial model, no kriging, no
sequential Gaussian simulation and no conditioning to drill data. Blocks have an INDEX and a BENCH,
not coordinates, and "adjacent" has no meaning here beyond consecutive in the dig order. It is NOT a
mine schedule: there is no pushback, no period, no cutoff and no destination policy, and although the
CCG study it cites routes loads to separate stockpiles by an SMR threshold, that routing lives in
`design.Area` and `sectors.py`, not here. It does NOT perturb grades by the ore-control uncertainty:
the 0.12 rides along as declared metadata. And it does NOT model a fleet: there is no queue, no cycle
time, no spot time and no shovel productivity, so `n_loads` is a count and never a rate.

---

## 10. API summary

Everything in the table is exported at the package root (`import bedblend as bb`), verified with
`hasattr`.

| Name | Kind | Returns |
|---|---|---|
| `Xorshift(seed)` | class | `.uniform()` in [0, 1), `.normal()` standard normal |
| `DigBlock(index, grade, n_loads, bench=0)` | frozen dataclass | one ore-control block |
| `DigSequence(blocks)` | frozen dataclass | `.n_loads` property |
| `dig_sequence(*, n_loads, seed, ...)` | function | `DigSequence` |
| `payloads_from(seq, *, seed, ...)` | function | `list[Payload]` in dig order |
| `measured_range_t(payloads, *, n_lags=30)` | function | practical range in tonnes, or a silent cap |
| `cumulative_tonnes(payloads)` | function | `list[float]`, running tonnage after each load |

Minimal use. The first line is the repository README's quickstart verbatim; the README does not call
`measured_range_t` anywhere, so the second line belongs to this document:

```python
import bedblend as bb

loads = bb.payloads_from(bb.dig_sequence(n_loads=600, seed=7), seed=7)
print(len(loads), "loads,", round(bb.measured_range_t(loads)), "t practical range")
# 600 loads, 6952 t practical range
```

That printed 6952 t is CENSORED, and it is a fair illustration of section 6 rather than a good
example to copy. The cap at the default `n_lags=30` for this stream is 6952.3 t, so the function
looked at every lag it was allowed and never reached 95 percent of the variance. Raising `n_lags`
gives 23 174 t at 100 and 46 349 t at 200, both still exactly at their caps, and only at
`n_lags=300` does the value settle at 51 502 t and stop moving. The honest one-liner is longer than
the pretty one: compare the return against `min(n_lags, len(loads) // 2) * mean_tonnes` every time.

---

## References

Only sources the code itself cites appear here. Where a citation in the source lacks a DOI, that is
stated rather than filled in.

* Neufeld, C., Lyall, G. and Deutsch, C.V. (2006), CCG Report 8, paper 306. The sequential-dig
  simulation this module's mechanism is taken from, including the quoted sentence about material from
  a single grade block arriving spatially correlated, mining by pushback and by pit with the top
  bench first, and two adjacent blocks loaded into each truck. Cited in `bedblend/stream.py` and
  `bedblend/sectors.py`. CCG annual reports do not carry DOIs.
* Young, A. and Rogers, W.P. (2021), Minerals 11(6), 636.
  [doi:10.3390/min11060636](https://doi.org/10.3390/min11060636). Section 1.6 is the source of the
  5 to 20 percent ore-control misclassification band and the 9 to 19 percent ore loss from blast
  movement and dilution, which is what `grade_uncertainty` carries. Cited in `bedblend/stream.py` by
  volume and article number; the DOI is the one in the repository README for the same paper.
* Young, A. and Rogers, W.P. (2022), Mining 2(1).
  [doi:10.3390/mining2010006](https://doi.org/10.3390/mining2010006). The dumping study whose CAT
  793F is the source of the 231 t default payload, via `TruckSpec` in `bedblend/terrain.py`. The
  repository disagrees with itself on the page range (86-102 in `terrain.py`, 92-114 in the README).

---

## See also

* `docs/methods/09_blending-metrics.md` for the metrics that consume this stream, the direction of
  the variance reduction ratio, and the `1/N` bound this module decides the reachability of.
