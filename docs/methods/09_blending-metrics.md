# Method 9: blending metrics, the verdict

Source read for this document: `bedblend/blending.py`, `bedblend/rtd.py`, `bedblend/sectors.py`.
Gates: `tests/test_blending.py`, `tests/test_build.py`, `tests/test_blocks_sectors.py`. Every number
below was produced by running the installed package, and the run that produced the end-to-end figures
is described in full in the section "The worked run" so it can be reproduced.

This is the module that decides whether the pile was worth building. Everything upstream of it
(terrain, routing, dumping, relaxation, dozing, the ledger, reclaim) exists to produce two number
sequences: the grades that went in and the grades that came out. This module turns those two
sequences into a verdict, states how far that verdict is from the best a pile of that many layers
could possibly do, and describes the shape of the stream rather than only its spread.

---

## 1. The direction of the ratio, and why it is pinned by a test

The definition, and the constant the package exports so that no surface can render a number without
rendering the convention beside it:

```
VRR = var_out / var_in                LOWER IS BETTER

VRR_FORMULA_LABEL == "VRR = var_out / var_in (lower is better)"

    var_in    tonnage-weighted variance of the grade of the loads ARRIVING at the pile
    var_out   tonnage-weighted variance of the grade of the cuts LEAVING the pile
    VRR = 1   the pile did nothing
    VRR = 0   the outgoing stream is perfectly uniform
```

The reciprocal convention (`var_in / var_out`, higher is better) circulates in secondary sources. It
is not a harmless alternative here: adopting it inverts every number the package produces and makes
any recommendation layer built on top of it advise the worse stacking method with apparent
confidence. The module header names this as the reason `VRR_FORMULA_LABEL` exists at all, though it
spells the constant `vrr_formula_label` in lowercase; the exported name is upper case and grepping
for the header's spelling finds nothing.

The direction is therefore held by a test rather than by a comment:
`tests/test_blending.py::test_vrr_is_out_over_in_so_lower_is_better`. It asserts that
`vrr(var_in=1.0, var_out=0.121)` is strictly less than `vrr(var_in=1.0, var_out=0.232)`, that the
first equals 0.121 to within 1e-12, and that the string `"var_out / var_in"` appears in
`VRR_FORMULA_LABEL`. The two magnitudes are the published pair the module cites: cone shell 0.232
against chevcon 0.121, from Loubser and de Korte, whose own text concludes that chevcon "has proven
to deliver much better consistency". Under the reciprocal convention those become 4.31 and 8.26 and
the better method is the larger number, which is precisely the inversion the test forbids.

The size of the trap is easy to feel with the real numbers from the worked run below: the correct
ratio is `0.001569 / 0.034892 = 0.04498`, and the reciprocal is `22.232`. Both are plausible-looking
outputs. Only one of them means "the pile removed most of the variance".

Running the functions, verified:

```
vrr(1.0, 0.121)  ->  0.121
vrr(1.0, 0.232)  ->  0.232
vrr(0.0, 0.3)    ->  inf      no variance in, so nothing to reduce, reported as infinity
vrr(1.0, 0.0)    ->  0.0      a perfectly uniform output is a legitimate zero, not a guard
```

The `var_in <= 0` guard returns `math.inf` rather than raising. This is deliberate and it is a
sharp edge for the caller: a constant input stream produces an infinite VRR, which propagates through
`blending_efficiency` (it returns 0.0 for a non-finite achieved VRR) but will render as `inf` if the
consumer formats the raw ratio.

---

## 2. Both variances on the same base

Kumral's requirement, as the module header states it, is that both variances be computed over equal
tonnages rather than equal counts. This is easy to violate by accident because dumps and cuts do not
come in the same size: a truckload is about 231 t while the reclaim cuts in the worked run run from
3000 t down to 10.8 t, averaging 1702 t. `tonnage_weighted_variance` is consequently the only
variance function in the module. There is no unweighted variant to reach for.

```
mean = sum_i (w_i * v_i) / sum_i w_i

var  = sum_i (w_i * (v_i - mean)^2) / sum_i w_i

    v_i   the value of observation i (a grade)
    w_i   the tonnage observation i speaks for
```

This is a POPULATION variance on the tonnage base. There is no `n - 1` and no
`sum(w) - sum(w^2)/sum(w)` reliability correction. It is not an estimator of a superpopulation
variance; it is the dispersion of the material that actually moved, which is the right quantity for a
ratio of two realised streams.

Checked behaviour:

```
tonnage_weighted_mean([1.0, 3.0], [1.0, 1.0])      ->  2.0
tonnage_weighted_mean([1.0, 3.0], [9.0, 1.0])      ->  1.2
tonnage_weighted_variance([1.0, 3.0], [1.0, 1.0])  ->  1.0
tonnage_weighted_variance([1.0, 3.0], [9.0, 1.0])  ->  0.36
tonnage_weighted_variance([], [])                  ->  0.0
```

`tests/test_blending.py::test_variance_is_tonnage_weighted_not_count_weighted` pins only the variance
lines, the third of those: it asserts the equal-weight case is 1.0 to within 1e-12 and that the
skewed weighting pulls it below that. It never calls `tonnage_weighted_mean`, so the mean values
above are checked here and nowhere else.

Two guard behaviours a maintainer should know. A non-positive weight total returns `0.0` rather than
raising, so a caller who passes all-zero weights gets a silent zero variance and therefore a silent
`VRR = 0`, which reads as perfect blending. And both functions zip with `strict=True`, so a
values/weights length mismatch raises `ValueError` rather than truncating (`zip() argument 2 is
shorter than argument 1` when the values are longer, `longer` when the weights are). The strictness
is the desirable half of that pair; the zero-weight silence is not guarded.

Two things about the worked run below make its own use of this function worth reading closely, and
neither is a general reassurance about the tonnage base.

The input side of that run is not really tonnage-weighted at all. `LoadRecord` carries no tonnage
field, verified against `dataclasses.fields`: it has `seq`, `grade`, `source_block`, geometry and
routes, and no `tonnes`. So the script weights the incoming grades by the nominal `231.0` for every
load, which is a constant and therefore identical to count-weighting. Recovering the real per-load
tonnes by joining `LoadRecord.seq` back to the `Payload` list moves `var_in` from `0.034892` to
`0.034894`, 0.007 percent, because `truck_spread` is only 6 percent. The lesson is not that the base
does not matter, it is that on the input side of a single-fleet build there is nothing for it to do.

The output side is where the cuts are genuinely unequal, and it still barely moved. The campaign
produced fifteen full 3000 t cuts, then a collapsing tail as the face ran out: 2751, 683, 688, 705,
475, 474, then nine cuts between 10.8 t and 55 t. That is a factor of 278 between the largest and
the smallest. Count-weighting the outgoing cuts nevertheless gave `var_out = 0.001552` against
`0.001569` tonnage-weighted, so `VRR = 0.04447` against `0.04498`, about one percent. The tail cuts
are numerous enough to take 30 percent of the count weight and 0.58 percent of the tonnage weight
(296.4 t of 51 072.9 t), and
the one-percent outcome is a coincidence of where their grades happened to sit relative to the mean.
Do not read it as evidence that the base is negligible; read it as one campaign where it was.

---

## 3. Mixing effect, the same quantity in the literature's units

```
E = sigma_in / sigma_out = sqrt(var_in / var_out)          HIGHER IS BETTER

    sigma  standard deviation, the square root of the corresponding variance
```

`mixing_effect(var_in, var_out)` exists because the only quantified anchor for a REAL bed is
published in this form, not as a VRR. Converting the package's own result into the anchor's units is
what makes the comparison against that anchor honest rather than approximate. Note that `E` and `VRR`
are the same information: `E = 1 / sqrt(VRR)`.

Verified guards and values:

```
mixing_effect(1.0, 0.04)   ->  5.0        pinned by test_the_ideal_bound_is_one_over_n
mixing_effect(1.0, 0.121)  ->  2.8748
mixing_effect(1.0, 0.232)  ->  2.0761
mixing_effect(1.0, 0.0)    ->  inf        checked FIRST, so a zero output wins over a zero input
mixing_effect(0.0, 0.1)    ->  0.0
```

The order of the two guards is load-bearing and is worth reading in the source: `var_out <= 0` is
tested before `var_in > 0`, so `mixing_effect(0.0, 0.0)` returns `inf`, while `vrr(0.0, 0.0)` returns
`inf` as well. The two functions agree on that degenerate case by coincidence of guard ordering, not
by a shared code path.

---

## 4. The ideal bound, and what the gap to it means

If the `N` layers a reclaim cut crosses were independent draws from the input distribution, then the
mean of the cut is the mean of `N` independent draws, and:

```
var(cut mean) = var_in / N

so     VRR_ideal = 1 / N          and      E_ideal = sqrt(N)
```

That is the whole derivation. The module says so explicitly, and says why it is derived rather than
cited: the De Wet (1994) design equation that the literature quotes for this relationship could not
be verified (Bulk Solids Handling 14(1) p. 93 is not available online, and the equation appears as a
rasterised image in the one paper that quotes it). It is therefore NOT reproduced and NOT attributed
anywhere in this package. What ships is the first-principles bound, labelled as derived.

```
vrr_ideal(25.0)   ->  0.04
vrr_ideal(100.0)  ->  0.01
vrr_ideal(200.0)  ->  0.005
vrr_ideal(600.0)  ->  0.0016667
vrr_ideal(0.0)    ->  inf
vrr_ideal(-5.0)   ->  inf        any non-positive N, not only zero
```

`blending_efficiency(achieved_vrr, n_layers)` reports the fraction of that ideal actually recovered:

```
efficiency = VRR_ideal / VRR_achieved,  clamped to at most 1.0

           = (1 / n_layers) / achieved_vrr

returns 0.0 when achieved_vrr is not finite, is <= 0, or when n_layers <= 0
```

This is the number that keeps the reporting honest. An achieved VRR quoted alone invites comparison
against zero. Quoted against the bound, a bed at `VRR = 0.05` over 100 layers is recovering
`blending_efficiency(0.05, 100)`, which returns `0.19999999999999998`, one fifth of what 100
independent layers would have given. That is the claim the docstring makes ("only recovering a
fifth") and it verifies to the last representable digit.

**Real beds do not come close, and the shortfall is squared on this scale.** Schramm (AT MINERALS
PROCESSING 06/2021) reports a mixing effect of 5 to 7.5 for beds of 200 to 600 layers. The ideal
`sqrt(N)` for those layer counts is 14.142 and 24.495, so on the `E` scale a real bed recovers
roughly a third of the ideal. On the VRR scale, which is a variance scale, that becomes:

```
N = 200, E = 5.0   ->  achieved VRR 0.04       ->  efficiency 0.125
N = 600, E = 7.5   ->  achieved VRR 0.017778   ->  efficiency 0.09375
```

The relationship is exact and worth stating because the two scales get confused: for the worked run
below, `E = 4.71508`, `E_ideal = sqrt(30) = 5.47723`, `(E / E_ideal)^2 = 0.741065`, and
`blending_efficiency = 0.741065`. Identical to six decimal places, because efficiency IS the square
of the mixing-effect ratio. So "a third of the ideal" on the `E` scale is "a ninth of the ideal" on
the efficiency scale, and the two statements are the same fact.
`tests/test_blending.py::test_efficiency_is_capped_at_one_and_reports_the_published_shortfall`
encodes the 0.125 and 0.09375 figures as an upper bound of 0.35, so a future change that quietly
starts reporting near-ideal blending for a real bed fails there.

Why real beds fall short, per the module header: successive layers are autocorrelated, a cut does not
sample every layer equally, and segregation biases what each cut contains. The first of those is the
one this package lets you move directly, through the shovel dwell in `stream.py`. See
`docs/methods/10_stream-synthesis.md`.

### The cap on the efficiency is not cosmetic, and N is your problem

`blending_efficiency` ends in `min(1.0, ideal / achieved_vrr)`. A finite realisation can genuinely
beat the `1/N` bound through sampling noise, and it can also appear to beat it because the caller
supplied a wrong `N`. Both look the same from outside: a flat 1.0.

**Nothing in this package computes `n_layers`.** Grepping the source, `n_layers` appears only as a
parameter of `vrr_ideal` and `blending_efficiency`, and no function anywhere returns one. There is no
test pinning what a layer means for a truck-built pile. The caller supplies the number, and the
result is only as meaningful as that number. The raw material for computing it does exist:
`BlockModel.columns[c]` is a list of `Parcel`, each carrying a `lift` and an `event_id`, and
`Cut.cells` records which columns a cut engaged, so a caller can count distinct parcels or distinct
lifts intersected by a cut. Doing so is out of scope for the engine as it currently stands, and any
consuming product that reports an efficiency must document which counting rule it used.

How badly a wrong `N` distorts the answer, using the worked run's achieved VRR at full precision,
`0.04498025...` (feeding the rounded `0.0450` instead shifts every row in the fourth decimal, which
is its own small lesson about quoting these):

```
N =  20   ->  efficiency 1.0        capped, the bound was beaten
N =  22   ->  efficiency 1.0        capped
N =  23   ->  efficiency 0.9666
N =  25   ->  efficiency 0.8893
N =  30   ->  efficiency 0.7411
N =  40   ->  efficiency 0.5558
N = 100   ->  efficiency 0.2223
```

The crossover is at `N = 1 / 0.04498 = 22.23`. Below it the metric is pegged at 1.0 and reports
nothing at all. A consuming product that shows "100 percent of ideal" is more likely to be showing a
layer count that is too small than a pile that is perfect.

---

## 5. The variogram: the shape of the stream, not just its spread

Variance is one number. Two streams with identical variance can have completely different structure,
and the structure is what decides whether layering helps. `experimental_variogram` computes
Matheron's experimental semivariogram of a one-dimensional stream:

```
gamma(h) = ( 1 / (2 * N(h)) ) * sum over pairs (i,j) with |p_j - p_i| in lag bin h  of  (z_i - z_j)^2

    z_i    the value at observation i (a grade)
    p_i    the POSITION of observation i, in tonnes
    N(h)   the number of pairs falling in that lag bin
    gamma  the semivariance, which rises from a nugget toward a sill as h grows
```

**`positions` is cumulative tonnage, not clock time.** A stockpile's input is a one-dimensional lot
in Gy's sense and its heterogeneity is a function of mass along the stream. Using time would make the
variogram depend on how busy the shift was: the same ore dug at half the rate would report double the
range. `stream.cumulative_tonnes` produces the right axis directly.

Signature and defaults, verified by `inspect.signature`:

```python
experimental_variogram(
    values: list[float],
    positions: list[float],
    n_lags: int = 20,
    max_lag: float | None = None,
) -> tuple[list[float], list[float], list[int]]
```

`max_lag` defaults to `span / 3.0` where `span = positions[-1] - positions[0]`. Bin width is
`max_lag / n_lags` and the returned lag centres are `(b + 0.5) * width`. On the worked stream
(600 loads, 138 565 t total) the default gives a largest lag centre of 44 961 t against a
`span / 3` of 46 114 t, which is `19.5 / 20` of it as the formula requires.

The return is a three-tuple `(lag_centres, gamma, pair_counts)`. Pair counts are returned rather than
discarded so a caller can grey out a noisy tail instead of silently trusting it. The docstring
suggests 30 pairs as the threshold below which a lag is untrustworthy. Note that `fit_spherical`
uses a different and much lower threshold of 5. That mismatch is in the source as written; the
docstring number is guidance to the plotting caller, the 5 is the fitter's own inclusion rule.

Measured on a real dig-sequence stream (600 loads, seed 5, dwell 25, `n_lags=24`):

```
lag centres     960.7 t  ..  45 153.2 t
sum of counts   99 544 pairs
gamma[0]        0.004510        gamma[-1]  0.032198
counts[0]       4750            counts[-1] 3370
series variance 0.032625        series mean 0.68667
```

`tests/test_blending.py::test_variogram_recovers_the_dig_sequence_structure` builds exactly this
stream and gates its shape, though loosely: 24 lags, more than 1000 pairs, `gamma[0] < gamma[-1]` so
the semivariogram must rise, and then a `fit_spherical` on it with `sill > 0` and `range > 0`. Note
what that does NOT pin. The measured values above are three orders of magnitude clear of the
thresholds (99 544 pairs against 1000), and no assertion touches the magnitude of the sill, the
nugget or the range, so the fit could drift a long way before this test noticed.

### Where it fails

**Positions must be non-decreasing.** The inner loop breaks out as soon as `h >= hmax`, which is only
correct for a sorted position array, and a negative `h` produces a negative bin index that Python
happily wraps. Verified on a six-point series: with sorted positions the result is
`counts = [0, 5, 0]`; with the same values and a mildly shuffled position array the result is
`counts = [0, 0, 0, 4, 0, 0]`, silently wrong; with a more strongly shuffled array it raises
`IndexError: list index out of range`. There is no assertion protecting this.
`cumulative_tonnes` always produces a non-decreasing array for positive tonnages, so the intended
call path is safe, and any other call path is the caller's responsibility.

**A short `positions` list raises `IndexError`, not `ValueError`.** The function indexes rather than
zipping, so unlike the weighted-moment functions it does not get the `strict=True` protection.

**It is quadratic.** The double loop is `O(n^2)` with an early `break`. Timed at the default
`n_lags` on one developer machine, so read the RATIOS rather than the absolute figures: 200 loads in
0.0011 s, 600 in 0.0101 s, 1200 in 0.0409 s. Tripling the stream costs about nine times as much and
doubling it about four, which is the quadratic scaling with the `break` doing little. Fine for a
stream of a few thousand loads, not fine for a hundred thousand.

**Guards return empty.** Fewer than 4 values, or a non-positive span, returns `([], [], [])` rather
than raising.

---

## 6. `fit_spherical`: a deliberately coarse, deliberately deterministic fit

```
gamma(h) = c0 + c * ( 1.5 * (h/a) - 0.5 * (h/a)^3 )      for h < a
gamma(h) = c0 + c                                        for h >= a

    c0   nugget, the semivariance extrapolated to zero lag
    c    partial sill, the rise from nugget to sill
    a    range, the lag at which the model reaches its sill, in tonnes
    returned dict keys: "nugget" = c0, "sill" = c0 + c, "range" = a, "rmse"
```

The fit is a grid search over `a` at 40 steps of `hmax / 40`, where `hmax` is the largest usable lag
centre. For each candidate range it solves a weighted linear least squares in `(c0, c)` with the pair
counts as weights, clamps any negative coefficient to zero, recomputes the weighted RMSE with the
clamped coefficients, and keeps the best.

The grid search is not laziness. The module states the reason: the objective is cheap, the free
parameter is one-dimensional and bounded, and a deterministic search gives byte-identical results
across the Python and the TypeScript implementations of this engine, which a gradient method with its
own convergence path would not. Determinism across lanes is a hard requirement in this package, not a
preference.

Inclusion rule: only lags with `count >= 5` and `h > 0` enter the fit, and fewer than four surviving
points returns `{"nugget": 0.0, "sill": 0.0, "range": 0.0, "rmse": 0.0}`, an all-zeros dictionary
that is indistinguishable from a genuine degenerate fit. Check the input length yourself if that
matters.

**The sill recovers the series variance, which is the check worth running.** On the 600-load stream
above (`n_lags=24`) the fitted sill was 0.032517 against a series variance of 0.032625, a 0.33
percent difference. Three more streams at 1000 loads, seed 13, this time at `n_lags=30`:

```
dwell 5    variance 0.02455   sill 0.02470   nugget 0.01813   range  5675.2
dwell 20   variance 0.03222   sill 0.02764   nugget 0.00129   range  5675.2
dwell 50   variance 0.03531   sill 0.03323   nugget 0.00025   range 15133.8
```

Quote the `n_lags` whenever you quote one of these. `experimental_variogram` defaults to `n_lags=20`,
not 30, and the same three streams at the default give sills 0.02468, 0.02762 and 0.03322 (close) but
nuggets 0.01377, 0.00025 and 0.00000 (not close at all, one of them an order of magnitude away). The
sill is the stable output of this fitter; the nugget and the range are not, and a number from it
without its lag count is not reproducible.

The nugget behaves as it should: a short dwell puts most of the structure below the first lag, so it
lands in the nugget. Feeding a larger within-block noise raises it directly, holding everything else
fixed (800 loads, seed 21, dwell 20, again `n_lags=30`): `within_block_sd = 0.0` gives nugget
0.003047, `0.02` gives 0.003492, `0.10` gives 0.005805. The same sweep at the default `n_lags=20`
gives 0.003621, 0.004092 and 0.004442, monotone in the same direction but not the same numbers.

**The range is quantised and can be blind.** It can only ever take one of 40 values, `hmax * k / 40`
for `k` in 1 to 40, where `hmax` is the largest lag centre that survived the inclusion rule. With
`max_lag` left at its `span / 3` default that largest centre is `((n_lags - 0.5) / n_lags) * span / 3`,
so the grid step is a shade under `span / 120` whatever `n_lags` is, which is coarse. Measured
consequence on the 1000-load seed-13 streams at `n_lags=30`, where the step is 1891.7 t: dwell 5 and
dwell 20 both came back with the IDENTICAL range of 5675.2 t, 3 grid steps, while
`stream.measured_range_t` on the same two streams returned 1082 t and 4430 t, correctly tracking the
dwells of 1155 t and 4620 t. At `n_lags=20` the two do separate (3751.4 t and 5627.1 t, 2 steps and
3 steps of 1875.7 t), which is the point rather than a rebuttal: the fitted range moved by 51 percent
on the dwell-5 stream for no reason but a change in the binning. If you want the correlation length
of the stream, use `measured_range_t` (documented in `docs/methods/10_stream-synthesis.md`). Use
`fit_spherical` for the sill, the nugget, and a plottable model curve.

The `rmse` in the returned dictionary is the weighted root mean square residual of the best fit, in
the units of gamma (grade squared). It is not normalised, so it is comparable across fits of the same
stream and not across streams of different variance.

---

## 7. Residence time: the pile as a buffer (`bedblend/rtd.py`)

A stockpile is not only a blender, it is a buffer between the pit and the plant, and its
residence-time distribution follows from its geometry and its reclaim rule. A freshly built cone
reclaimed from its face behaves close to last-in-first-out; a bedded pile reclaimed full-face behaves
close to a well-mixed first-in-first-out. Neither is exact. The module's position is that the honest
answer is the SHAPE of the distribution, placed between two references, rather than a label asserted
about the pile. (The `rtd.py` header words that second case as "a properly bedded chevron". Take it
as loose phrasing rather than a claim: the package docstring in `bedblend/__init__.py` states that
chevron beds are built by conveyor stackers and that offering them alongside trucks is a category
error this library once made. Nothing in `rtd.py` builds or assumes one.)

The three-way FIFO, LIFO and blended abstraction is the mine-planning industry's own vocabulary
(Micromine Alastri APS stockpile documentation, a vendor document with no DOI, cited as such in the
module header). Process-scale RTD in mineral processing is treated in Moraga, Kracht and Ortiz.

**Nothing in this engine produces residence times.** `Cut` carries tonnes, grade, provenance,
displacement, uncertainty, cells, coarse fraction, a stand, approach and departure polylines, the
grid cells behind those two polylines, and a loader position. It carries no timestamp. `LoadRecord`
likewise carries `seq` and no time field, so `BuildResult` records loads in sequence, not in seconds.
Every function in `rtd.py` therefore takes times from the caller, and the caller decides what a
second means. That is a design boundary, not an oversight, but it means an `rtd` panel in a consuming
product is reporting the product's own clock model and should say so.

Read the module header against that. It opens "WHAT IS COMPUTED. Each reclaim cut carries the
tonnage-weighted mean time its material spent in the pile." No cut carries any such thing; the field
does not exist. The header is describing a pipeline the engine does not have, and the six functions
in the module (`histogram`, `fifo_lifo_references`, `character`, `dimensionless_variance`,
`theoretical_plug_flow_variance`, `mean_and_sd`) are the whole of what it does have.

### `histogram`

```python
histogram(residences_s: list[float], weights_t: list[float], n_bins: int = 24) -> dict
```

Returns `{"edges", "mass", "cumulative", "mean_s", "var_s2"}`. Tonnage-weighted, for the same reason
the grade variance is: cuts are not all the same size and an unweighted histogram lets a small cut
speak as loudly as a large one. `mass` is normalised to sum to 1. `mean_s` and `var_s2` are computed
over the RAW residence list, not over the binned mass, so they do not carry binning error.

**Naming defect worth knowing before you plot it: the `"edges"` key does not contain edges.** The
source computes `[lo + (b + 0.5) * width for b in range(n_bins)]`, which is bin CENTRES, and there
are `n_bins` of them rather than the `n_bins + 1` a real edge array would have. Verified on
`residences_s = [100, 200, 300, 400, 500]`, `weights_t = [1000, 2000, 1000, 500, 500]`, `n_bins = 5`:

```
edges       [140.0, 220.0, 300.0, 380.0, 460.0]      lo=100, hi=500, width=80, so these are centres
mass        [0.2, 0.4, 0.2, 0.1, 0.1]
cumulative  [0.2, 0.6, 0.8, 0.9, 1.0]
mean_s      250.0
var_s2      14500.0
```

A plotting caller that treats these as edges will draw every bar half a bin width to the left. An
empty input returns the same keys with empty lists and zero moments. A values/weights length mismatch
raises `ValueError` from the strict zip.

`mean_and_sd(residences_s, weights_t)` returns the same two moments as a tuple, with the standard
deviation rather than the variance: `(250.0, 120.41594578792295)` on the data above, whose square is
14499.999999999998, the `var_s2` the histogram reported to within floating-point round trip.

### `fifo_lifo_references`

```python
fifo_lifo_references(
    dump_times_s: list[float], dump_tonnes: list[float],
    cut_times_s: list[float], cut_tonnes: list[float],
) -> dict            # {"fifo_mean_s": float, "lifo_mean_s": float}
```

Both references are computed by walking an explicit inventory queue rather than by a closed-form
approximation, so they are exact for the sequence they describe and stay valid when the stacking and
reclaim rates are not constant. Dumps are admitted to the stock when `dump_time <= cut_time`; a cut
then draws from the end of the list (LIFO) or the front (FIFO) until satisfied or until the stock is
empty, and a cut that cannot be satisfied simply takes what is there.

Hand-checkable worked example, verified by running it. Six dumps of 1000 t at times
0, 100, 200, 300, 400, 500 s; three cuts of 800 t at 250, 450, 650 s:

```
FIFO:  800 t aged 250 s
       200 t aged 450 s, 600 t aged 350 s
       400 t aged 550 s, 400 t aged 450 s
       total 900 000 t.s over 2400 t   ->  fifo_mean_s = 375.0

LIFO:  800 t aged  50 s
       800 t aged  50 s
       800 t aged 150 s
       total 200 000 t.s over 2400 t   ->  lifo_mean_s = 83.333
```

### `character`

```python
character(actual_mean_s: float, fifo_mean_s: float, lifo_mean_s: float) -> tuple[float, str]

position p = (actual_mean_s - lifo_mean_s) / (fifo_mean_s - lifo_mean_s),  clamped to [0, 1]

    p < 0.25   ->  "last-in-first-out"
    p > 0.75   ->  "first-in-first-out"
    otherwise  ->  "blended"
    |fifo - lifo| < 1e-9  ->  (0.5, "indeterminate")
```

`p = 0` is pure LIFO and `p = 1` is pure FIFO. The band labels are DESCRIPTIVE and the module says so
in its own docstring: there is no published threshold that makes 0.6 "mostly first-in-first-out", and
pretending otherwise would be an invented number. The boundaries land on "blended": verified,
`p = 0.25` and `p = 0.75` both return "blended", and out-of-range inputs clamp rather than
extrapolate.

**Argument-order trap.** The signature is `(actual, FIFO, LIFO)` while the position formula is
anchored on LIFO, so the two reference arguments are easy to swap and the swap is silent. Verified:
on the worked example above, passing the LIFO mean as the actual value in the correct order gives
`(0.0, "last-in-first-out")`; passing the same value with `fifo` and `lifo` transposed gives
`(1.0, "first-in-first-out")`. The exact opposite verdict, no error, no warning. Unpack
`fifo_lifo_references` by key, never by position.

### `dimensionless_variance` and `theoretical_plug_flow_variance`

```
sigma^2 / tau^2

    tau      the mean residence time, "mean_s"
    sigma^2  the variance of the residence time, "var_s2"

    0   ideal plug flow
    1   an ideal perfectly mixed tank
```

This places the pile on the reactor-engineering scale that process readers already think in.
Verified against both endpoints. The perfectly-mixed end, using the exponential quantiles at unit
weight so the check is reproducible rather than a random draw:

```python
vals = [-300.0 * math.log((k + 0.5) / 400) for k in range(400)]
mean, sd = rtd.mean_and_sd(vals, [1.0] * 400)          # 299.74, 298.13
rtd.dimensionless_variance(mean, sd * sd)              # 0.9893, against the ideal 1.0
```

The plug-flow end: a constant 300 s residence returns exactly 0.0. On the histogram example above the
value is 0.232. `mean_s <= 0` returns 0.0.

`theoretical_plug_flow_variance(mean_s)` is `0.0 * mean_s`, kept explicit so the comparison panel has
something to call rather than hard-coding a zero. It returns `nan` for an infinite argument, which is
a curiosity rather than a problem.

### What is not exported

`bedblend/__init__.py` re-exports `character`, `dimensionless_variance`, `histogram` and
`mean_and_sd` at the package root. It does NOT export `fifo_lifo_references` or
`theoretical_plug_flow_variance`, verified with `hasattr`. Since `character` is useless without the
two references it compares against, a caller who imports only from the package root has half the
tool. Import `from bedblend.rtd import fifo_lifo_references` explicitly.

---

## 8. Sector rollups (`bedblend/sectors.py`), briefly

The industry baseline this layer exists to beat is stated plainly in the paper the module cites: "the
resulting stockpile block model currently in place is merely one large, homogenized block value
containing the rolling average grade". One number for the whole pile. Everything above one number is
what these rollups are for.

There are two levels, and the content is the disagreement between them. RAW is the per-column ledger
in `blocks.py`, at truckload support. SECTOR is a named working region (`design.Area`), its
tonnage-weighted rollup, and its uncertainty. Sectors arise two ways, both modelled: by ROUTING
before placement (each load classified from its ore-control estimate and sent to a designated area,
per the CCG 2006 study which routed high SMR against low SMR on a threshold of 1.75), and by ANALYSIS
after placement (partitioning the built pile into quadrants). The source never expands the acronym
"SMR", in `sectors.py` or anywhere else in the package, so neither does this document.

```python
Rollup(name, tonnes, mean_grade, stdev, n, ci)      # ci: dict[float, float]
Rollup.interval(level=0.95) -> (mean - half_width, mean + half_width)

CONFIDENCE_LEVELS == (0.90, 0.95, 0.99)
z-values used:  1.6448536269514722, 1.959963984540054, 2.5758293035489004
```

The mean and the standard deviation are tonnage-weighted, exactly as in `blending.py`. The
CONFIDENCE INTERVAL IS NOT. The half-width is `z * sd / sqrt(n)` where `n` is the COUNT of
observations, and the source says why in a comment: the weights express how much material each
observation speaks for, not how many independent measurements were made. Using the tonnage total
there would make the interval collapse with pile size rather than with sample size. This is the
subtlest decision in the module and it is easy to "fix" wrongly.

The five entry points are `rollup(model, terrain, area, *, name=None)`,
`rollup_by_lift(model, terrain, area, lift)`, `compare(model, terrain, area, observations)`,
`quadrants(area)` and `homogeneity_map(model, terrain, *, window=3)`. All five are exported at the
package root, and `compare` also has the alias `sectors_compare` because `compare` is a very generic
name to occupy at a package root.

From the worked run, before the reclaim campaign drained the pile:

```
sector "ROM"     n 1296 columns, 46 641.5 t, mean grade 0.7511, sd 0.0529
   90 percent half-width 0.002418      interval (0.7487, 0.7535)
   95 percent half-width 0.002881      interval (0.7482, 0.7540)
   99 percent half-width 0.003786      interval (0.7473, 0.7549)
rollup_by_lift lift 0   n 1296, 46 641.5 t, mean 0.7511
rollup_by_lift lift 1   n 0, 0.0 t             the plan scheduled two benches; one was built
```

That empty lift 1 is worth pausing on. `rollup_by_lift` returns a zero-filled `Rollup` for a lift
that holds nothing, not `None` and not an error, so a panel iterating lifts will render a sector with
a mean grade of 0.0 unless it checks `n > 0` first.

`compare` reproduces the published raw-versus-model comparison, and the qualitative result it must
reproduce is that the model's interval is narrower than the data's in every region, because
interpolation averages. Verified on all four quadrants of the worked run, with the observations taken
as `(r.x_m, r.y_m, r.grade)` per `LoadRecord` and, critically, run BEFORE the reclaim campaign:

```
                    data                        model
ROM bottom left     n  98, sd 0.2062, ci95 0.04082    n 324, sd 0.0400, ci95 0.00435
ROM bottom right    n  65, sd 0.1761, ci95 0.04282    n 324, sd 0.0510, ci95 0.00556
ROM top left        n  60, sd 0.1396, ci95 0.03532    n 324, sd 0.0492, ci95 0.00536
ROM top right       n  28, sd 0.1370, ci95 0.05074    n 324, sd 0.0593, ci95 0.00646
```

**`campaign` mutates the model in place, and the sector numbers are not the same on either side of
it.** The 324 in each model column is the full 18 by 18 quadrant of a 36 by 36 column area, every one
of them holding material. Run the identical four `compare` calls after the campaign has drained
51 072.9 t and the model side reads n 47, 48, 95 and 94, with the standard deviations up (0.0612,
0.0771, 0.0497, 0.0722) and the intervals two to four times wider, because what is left is the
unreclaimed remainder rather than the pile. The whole-area `rollup` drops from n 1296 to n 284 the
same way. Nothing warns you. Any panel comparing sectors has to state which side of the reclaim it
sampled.

`tests/test_blocks_sectors.py::test_model_interval_is_tighter_than_the_data_in_every_quadrant` and
`tests/test_build.py::test_sector_rollup_and_the_published_comparison_hold_on_a_real_build` gate
this. Note that the reassurance runs the wrong way: the model looking tighter is exactly the reason a
sector rollup can read as confident while the raw field underneath it is not.

`homogeneity_map` computes the local standard deviation of column grades in a
`(2 * window + 1)` square neighbourhood, returning `None` where fewer than three neighbouring columns
hold material rather than a zero that would read as perfect uniformity. On the worked run with the
default `window=3`, 2342 of 4096 cells returned a value, ranging from 0.0 to 0.23784.

---

## 9. The worked run

Every end-to-end number above came from one script, run against the source tree with the package's
own `.venv` interpreter. Reproduce it as follows:

```python
from bedblend.blending import (blending_efficiency, mixing_effect,
                               tonnage_weighted_mean, tonnage_weighted_variance, vrr, vrr_ideal)
from bedblend.build import build
from bedblend.design import rectangular_yard
from bedblend.reclaim import ReclaimFace, ReclaimMethod, campaign
from bedblend.sectors import compare, quadrants, rollup
from bedblend.stream import dig_sequence, payloads_from
from bedblend.terrain import Terrain, TruckSpec
from bedblend.truck import Fleet

REPOSE = 37.0
loads = payloads_from(dig_sequence(n_loads=240, seed=7, loads_per_block=20), seed=7)
terrain = Terrain.flat(64, 64, 2.5)
plan = rectangular_yard(n_areas=1, area_width_m=90.0, area_length_m=90.0,
                        bench_height_m=8.0, n_benches=2, classes=["ROM"])
plan.row_spacing_m = 10.0
plan.tip_spacing_m = 8.0
plan.loads_per_dozer_pass = 40
plan.areas[0].access_xy = (90.0, 90.0)
fleet = Fleet.of(4, TruckSpec(), (140.0, 140.0), repose_deg=REPOSE)
res = build(terrain, plan, fleet, loads, repose_deg=REPOSE, verify_every=50)

# THE SECTOR NUMBERS IN SECTION 8 ARE TAKEN HERE, BEFORE THE CAMPAIGN. campaign() drains the model
# in place, so running these after it reports the remainder rather than the pile.
area = plan.areas[0]
obs = [(r.x_m, r.y_m, r.grade) for r in res.placed]
print(rollup(res.model, res.terrain, area))
for q in quadrants(area):
    print(compare(res.model, res.terrain, q, obs))

face = ReclaimFace(method=ReclaimMethod.FULL_HEIGHT, position_m=0.0, direction=(1.0, 0.0),
                   depth_m=10.0, width_m=200.0, max_face_m=15.0)
cuts = campaign(res.terrain, res.model, face, cut_tonnes=3000.0, n_cuts=30, repose_deg=REPOSE)

# 231.0 rather than the real payloads because LoadRecord carries no tonnage field. That makes the
# input side count-weighted in effect; see section 2 for how little it costs here (0.007 percent).
var_in = tonnage_weighted_variance([r.grade for r in res.placed], [231.0] * len(res.placed))
var_out = tonnage_weighted_variance([c.grade for c in cuts], [c.tonnes for c in cuts])
print(vrr(var_in, var_out), mixing_effect(var_in, var_out))
```

Results, on a build that took 9.7 seconds:

```
240 loads placed, refusal rate 0.0
30 cuts, 51 072.9 t reclaimed of 55 440.0 t placed
cut tonnages   15 at the full 3000 t, then 2751, 683, 688, 705, 475, 474,
               and nine between 10.8 t and 54.8 t as the face ran out

mean_in   0.748868    var_in   0.034892    sd_in   0.186794
mean_out  0.750907    var_out  0.001569    sd_out  0.039616

VRR   0.044980        E   4.715075
```

The means agree to 0.002039, which is the sanity check that the reclaim did not lose or invent metal.
The standard deviation fell from 0.186794 to 0.039616, a factor of 4.715, which is the mixing effect.
Whether 0.04498 is good depends entirely on `N`, and the package will not tell you `N`.

---

## 10. What this module is, and what it is not

It IS a set of evaluation metrics over two realised grade sequences, on a tonnage base, with the
convention pinned by a test and the ideal bound derived from first principles and labelled as
derived. It IS a variogram tool for describing the structure of the incoming stream in tonnes.

It is NOT a blending optimiser: it evaluates a pile and never chooses one. It is NOT plant metal
accounting: it stops at the reclaimed stream. It does NOT compute the layer count that its own ideal
bound requires. It does NOT model chevron, windrow or cone-shell beds; the cone shell and chevcon
numbers appear here only as the published pair that pins the direction of the ratio, and those beds
are built by conveyor stackers, not by the trucks this package models. `rtd.py` does NOT produce
residence times, only statistics over residence times the caller supplies. And the confidence
intervals in `sectors.py` are normal-quantile intervals on a mean with a count-based standard error;
they are not geostatistical estimation variances and carry no spatial model.

---

## References

Only sources the code itself cites appear here. Where a citation in the source lacks a DOI, that is
stated rather than filled in.

* Loubser, J.A. and de Korte, G.J. (2015), J. S. Afr. Inst. Min. Metall. 115(8), 773-780.
  [doi:10.17159/2411-9717/2015/v115n8a15](https://doi.org/10.17159/2411-9717/2015/v115n8a15).
  The source of the VRR definition, its direction, and the cone shell 0.232 against chevcon 0.121
  pair that the direction test is built on. Cited in `bedblend/blending.py`.
* Kumral (2006). Named in the `bedblend/blending.py` header as the origin of the same-tonnage-base
  requirement, following which Loubser and de Korte define VRR. The source carries no fuller
  citation and no DOI for it, so none is given here.
* Schramm, AT MINERALS PROCESSING 06/2021. The mixing effect of 5 to 7.5 for beds of 200 to 600
  layers, which is the only quantified anchor for a real bed in this package. Cited without a DOI in
  `bedblend/blending.py`; trade-magazine article.
* De Wet (1994), Bulk Solids Handling 14(1) p. 93. Cited in the source ONLY to record that it could
  not be verified and that its design equation is therefore deliberately not reproduced.
* Moraga, Kracht and Ortiz (2022), Minerals Engineering 187, 107807.
  [doi:10.1016/j.mineng.2022.107807](https://doi.org/10.1016/j.mineng.2022.107807). Process-scale
  RTD in mineral processing. Cited in `bedblend/rtd.py`.
* Micromine Alastri APS stockpile documentation. The source of the FIFO, LIFO and blended reclaim
  abstraction, cited in `bedblend/rtd.py` as vendor documentation. No DOI.
* Young, A. and Rogers, W.P. (2021), Minerals 11(6), 636.
  [doi:10.3390/min11060636](https://doi.org/10.3390/min11060636). `bedblend/sectors.py` cites it by
  volume and article number for TABLE 3 only, the raw-versus-model quadrant comparison that
  `sectors.compare` reproduces, and for the "one large, homogenized block value" baseline. The 5 to
  20 percent ore-control misclassification band from section 1.6 of the same paper is cited
  elsewhere, in `bedblend/stream.py` and `bedblend/truck.py`, and is documented in
  `docs/methods/10_stream-synthesis.md`, not here. The DOI is the one carried in the repository
  README for the same paper; the module docstrings give no DOI.
* Neufeld, Lyall and Deutsch (2006), CCG Report 8, paper 306. The routed-stockpile study behind the
  sector-by-routing model and the SMR threshold of 1.75. Cited in `bedblend/sectors.py`. CCG annual
  reports do not carry DOIs.

---

## See also

* `docs/methods/10_stream-synthesis.md` for where `var_in` comes from and why the autocorrelation of
  the incoming stream is what keeps the achieved VRR away from the `1/N` bound.
