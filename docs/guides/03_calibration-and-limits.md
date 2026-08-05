# Calibration and limits

This is the document that keeps the product honest. It lists every number in `bedblend` that is a
CHOICE rather than a measurement, says where the choice lives, what it is anchored to, and what
measurement would replace it. Then it lists, plainly, everything the engine does not model at all.

Every value below was read off the module at version `0.07.002` and every magnitude was produced by
running the engine, not recalled. Where a docstring in the repository disagrees with what the code
computes, this document says so and quotes the computed value.

## Four classes of number

**MEASURED.** Taken from a specific published study, with the study cited in the docstring that
carries the constant. The four dump profiles and their frequencies, the dump footprint envelope, the
2:1 fresh-heap slope. Changing one of these is disagreeing with a measurement.

**ANCHORED.** A defensible choice pinned to a published band, a rule of thumb or a reference case, but
not fitted to anything. `PERCOLATION_COEFFICIENT`, `PECLET_DEFAULT`, `CASCADE_FLUX_M2_S`, the truck
gradient divisor. These are the numbers a calibration campaign exists to replace, and every one of
them is a module-level named constant or a keyword argument precisely so that it can be seen and
changed rather than hidden in an expression.

**DERIVED.** Falls out of geometry or of another number and has no freedom. `Fleet.max_grade`,
`critical_drop`, `run_out_for_bench`, `TruckSpec.load_volume_m3`, `Bench.designed_volume_m3`,
`vrr_ideal`. These are not calibration targets; if one is wrong the formula is wrong.

**NUMERICAL.** Tolerances and discretisations that should not change any answer, only the cost and the
precision of getting it. `CFL`, `NZ_DEFAULT`, `CONVERGE_TOL_M`, `MAX_MOVES`. They belong in the
inventory because a numerical parameter that DOES change an answer has stopped being numerical, and
two of them are marked below where that is a live risk.

## The inventory

Every non-trivial literal in the engine, by module. Values are as of `0.07.002`.

### `facesegregation`

| Name | Value | Class | Anchor |
|---|---|---|---|
| `PERCOLATION_COEFFICIENT` | `0.30` | ANCHORED | Set so `Sr` for an 11 m face at 37 degrees in the default material lands near 1.8, inside the range of the source's worked examples |
| `CASCADE_FLUX_M2_S` | `1.0` | ANCHORED | A truck body emptying in about 10 s across about 10 m of crest, for a 100 m3 load, is of order 1 m2/s |
| `LAYER_MIN_DIAMETERS` | `5.0` | ANCHORED | A flowing layer cannot be thinner than a few grains before the continuum description stops meaning anything |
| `FLOW_HYSTERESIS_DEG` | `4.0` | ANCHORED | Published width of the start-stop hysteresis in granular flow, a few degrees |
| `REFERENCE_DROP_M` | `11.0` | MEASURED band | The operational guidance to limit conical stockpile height to 10 to 12 m |
| `FAST_FLOW_ANGLE_DEG` | `35.0` | MEASURED band | The published 35-to-40 against 30-to-35 face-angle split |
| `GRAVITY_M_S2` | `9.81` | DERIVED | Physics |
| overrun cap | `0.25` | ANCHORED | In `segregate_face`, "even a tall face does not throw most of its load off the toe". Marked in the source as an operational judgement |
| overrun coefficient | `0.30` | ANCHORED | Same expression |
| overrun length scale | `2 * REFERENCE_DROP_M = 22.0` m | ANCHORED | Same expression |
| cascade mass distribution | `w(s) = 0.35 + 0.65 s` | ANCHORED | The published statement that the cascade "aggregates more at the bottom ... and less near the top crest", turned into the simplest linear ramp |
| `intensity` angle window | `(angle - 28) / 12`, clamped | ANCHORED | Rises through the published 30-to-40 window and saturates |
| `segregate_face(n_bins=)` | `12` | NUMERICAL | Down-face resolution |

### `segregation`

| Name | Value | Class | Anchor |
|---|---|---|---|
| `PECLET_DEFAULT` | `12.0` | ANCHORED | Gray and Chugunov fit `Pe` against chute experiments and report values of order ten; held at the middle of that range |
| `NZ_DEFAULT` | `32` | NUMERICAL | Depth cells in the flowing layer |
| `CFL` | `0.4` | NUMERICAL | Courant number for the hyperbolic and the parabolic sub-step |

### `dump`

| Name | Value | Class | Anchor |
|---|---|---|---|
| `PROFILE_STATS[OVAL]` | volume 128.0 m3, angle 34.5 deg, width 14.8 m, thickness 1.00 m, n=12 | MEASURED | Mining 2022 table 5 and the per-type box charts |
| `PROFILE_STATS[COMET]` | 134.0, 33.5, 19.4, 1.50, n=6 | MEASURED | Same |
| `PROFILE_STATS[RECTANGULAR]` | 137.0, 34.0, 13.0, 0.95, n=4 | MEASURED | Same |
| `PROFILE_STATS[SLOUGHED_HEAP]` | 129.0, 24.5, 14.6, 1.40, n=6 | MEASURED | Same |
| `MEASURED_LENGTH_M` | `(13.0, 46.0)` | MEASURED | Whole-population range, table 5 |
| `MEASURED_WIDTH_M` | `(11.0, 23.0)` | MEASURED | Same |
| `MEASURED_THICKNESS_M` | `(0.368, 2.032)` | MEASURED | Same |
| `MEASURED_ANGLE_DEG` | `(12.0, 36.0)` | MEASURED | Same |
| `MEASURED_VOLUME_M3` | `(94.0, 155.0)` | MEASURED | Same |
| `SLOUGH_DISTANCE_TRUCK_LENGTHS` | `1.0` | ANCHORED | "Tip about one truck length back from an edge". Named in the source as a rule of thumb |
| `SLOUGH_EXTENT` | `0.85` | ANCHORED | Set so the realised sloughed-heap length lands on the measured mean, about 25 m against a 30 m run-out |
| oval width shape | `sin(pi s) ** 0.6` | ANCHORED | "narrow at crest and toe, maximum width midway" |
| comet width shape | `s ** 0.8` | ANCHORED | "large volume near the base, narrow trail extending up the face" |
| rectangular width shape | `1.0` | ANCHORED | "covers the whole dump face evenly to uniform width" |
| sloughed width shape | `sin(pi min(s/0.85, 1)) ** 0.5` | ANCHORED | Same |
| edge mass shape | `0.35 + 0.65 s` | ANCHORED | Same statement as in `facesegregation`, DUPLICATED in two modules |
| lateral taper | `1 - (t / half) ** 2` | ANCHORED | So the streak has edges rather than a cliff |
| paddock flat top | `r <= 0.4` | ANCHORED | Elliptical frustum with a flat top over the inner 40 percent |
| face angle clamp | `[1.0, 89.0]` deg | NUMERICAL | Guards `tan` |

### `truck` and `terrain`

| Name | Value | Class | Anchor |
|---|---|---|---|
| `Fleet.of(grade_limit_divisor=)` | `1.5` | ANCHORED | Named in TWO docstrings as a commonly repeated operational rule of thumb, explicitly NOT a measured constant |
| `Truck.discharge_xy` offset | `0.66 * body_length_m` | ANCHORED | Two thirds of a body length puts the release point just off the back of a rear-dump machine |
| `tip_reach` | `4.0 * cell_m` | ANCHORED | How far from a crest cell a tip still counts as at the face. Expressed in CELLS so it scales with pad resolution |
| crest re-orient radius (`spot`) | `3.0 * tip_reach = 12 cells` | ANCHORED | Beyond this the crest normal does not override the truck's own heading |
| `TruckSpec.payload_t` | `231.0` | MEASURED | CAT 793F, the machine in the companion dumping study |
| `TruckSpec.bed_width_m` | `7.334` | MEASURED | Inside bed width, same source |
| `TruckSpec.body_length_m` | `12.9` | ANCHORED | Approximate published figure for the class, stated as approximate in the source |
| `TruckSpec.dump_height_m` | `6.5` | ANCHORED | Same. Carried for reporting; nothing reads it |
| `TruckSpec.loose_density_t_m3` | `1.9` | ANCHORED | 1.6 to 2.2 t/m3 is the usual handbook band for blasted hard rock |
| `EMPTY_M` | `1e-4` | NUMERICAL | Above this a cell counts as carrying material |

### `build`

| Name | Value | Class | Anchor |
|---|---|---|---|
| `crest_drop_m` | `1.0` m | ANCHORED | Minimum drop for a cell to count as crest |
| `max_spot_offset_m` | `25.0` m | ANCHORED | How far from the planned tip a truck may spot, and it must stay inside the area |
| `paddock_frac` | `0.18` | ANCHORED | Fraction of a bench's designed volume laid as base layer. NOTE the mismatch below |
| at-face threshold | `3.0 * cell_m * 4.0 = 12 cells` | ANCHORED | Beyond this an edge-phase tip is treated as a heap |
| `seed` | `20260801` | NUMERICAL | Default seed, a date |
| dozer re-doze rate limit | `seq - last_doze >= 2` | ANCHORED | Stops a stretch of unreachable tips dozing once per load |
| `push_to_crest` in `_doze` | `depth_m=0.2`, `push_m=15.0` | ANCHORED | Call-site values, NOT the function defaults of 0.3 and 40.0 |
| `build_berm` in `_doze` | `height_m=0.4`, `source_depth_m=0.1` | ANCHORED | Call-site values, NOT the function defaults of 1.5 and 0.2 |

**The `paddock_frac` mismatch is real and worth knowing.** `build()` defaults it to `0.18` and passes
that down; `DumpPlan.bench_program()` and `DumpPlan.program()` both default it to `0.35`. So calling
the plan directly gives you roughly twice the base layer that a build does. `build`'s comment explains
the choice: setting it too high starves the edge campaign, the load budget is consumed in paddock
dumps and no face is ever formed to cascade over, so none of the cascade physics runs. The source that
describes the base layer as "a series of paddock dumps" does not quantify it, so both numbers are
exposed parameters with stated defaults rather than measurements.

### `design`

| Name | Value | Class | Anchor |
|---|---|---|---|
| `tip_spacing_m` | `3.0` | MEASURED | 50 loads dumped 3 m apart along a 150 m row (CCG 2006) |
| `row_spacing_m` | `25.0` | ANCHORED | "a site choice", defaulting to roughly two truck lengths so adjacent rows do not merge |
| `loads_per_dozer_pass` | `12` | ANCHORED | The CCG rule "dozed up the pile after two rows" made explicit, expressed in loads |
| `loads_per_full_pass` | `60` | ANCHORED | Berm and crest push are furniture, not access, so they run five times less often |
| `lift_thickness_m` | `1.5` | ANCHORED | A dump is of the order of a metre thick and the dozer spreads it |
| `sweep_advance_frac` | `0.6` | ANCHORED | How far the crest advances per sweep, as a fraction of run-out, so arcs overlap |
| `seed_frac_x`, `seed_frac_y` | `0.25`, `0.25` | ANCHORED | The measured pattern seeds near one corner and sweeps outward |
| seed cluster size | `max(3, n_tips // 20)` | ANCHORED | Enough loads to raise an initial crest |
| seed cluster radius | `0.25 * step` | ANCHORED | Same |
| `ramp_width_m` | `25.0` | ANCHORED | Dump design reserves ramps "of a suitable width" without a figure |
| `gap_m` | `20.0` | ANCHORED | Between areas in a yard |
| `margin_m` | `30.0` | ANCHORED | Offset from the pad origin. Before it existed, 221 of 766 planned tips were refused for having nowhere to land |
| `_frustum_m3` | prismatoid rule | DERIVED | Replaced a blunt 0.55 box fraction that asked a 60 m square to hold 51,500 m3 against a geometric capacity of 27,100 |

### `relax`

| Name | Value | Class | Anchor |
|---|---|---|---|
| `FRESH_HEAP_SLOPE` | `2.0` | MEASURED | "At the time of dumping, heaps maintain an approximate 2:1 slope" |
| `FRESH_HEAP_DEG` | `63.43494882292201` | DERIVED | `degrees(atan(2.0))` |
| `STABLE_TOL_DEG` | `4.0` | ANCHORED | See the long note below |
| `BARE_M` | `1e-3` | ANCHORED | Below this a cell is physically bare and is exempt from the repose check |
| `VERIFY_TOL_M` | `1e-6` | NUMERICAL | Verifier tolerance, looser than the solver's |
| `CONVERGE_TOL_M` | `1e-9` | NUMERICAL | Solver tolerance |
| `MAX_MOVES` | `2_000_000` | NUMERICAL | Backstop, "a converged cascade uses a tiny fraction of this" |
| sweep cap in `relax_to` | `40` | NUMERICAL | Backstop against pathological oscillation, not the expected exit |
| `_NBR_CACHE` cap | `16` geometries | NUMERICAL | A session sweeps few pad geometries |

### `dozer`

| Name | Value | Class | Anchor |
|---|---|---|---|
| `DEFAULT_PUSH_M` | `40.0` | ANCHORED | Typical efficient push distance for a large track dozer; beyond it an operator rehandles. Named as operational, not measured |
| `DEFAULT_BLADE_M3` | `30.0` | ANCHORED | Blade capacity per pass |
| `level(tolerance_m=)` | `0.05` | NUMERICAL | Dead band around the target elevation |
| `level` transfer cap | `0.5 * height difference` | DERIVED | A push can never invert a pair, which is also what makes convergence provable |
| `build_berm(height_m=)` | `1.5` default, `0.4` at the call site | ANCHORED | See the `build` table |
| `build_berm(gap_every=, gap_cells=)` | `8`, `3` | ANCHORED | A continuous berm walls the area off from itself: refusals went UP as the dozer ran more often, 62 percent at a pass per 10 loads against 33 percent at a pass per 40 |
| `build_ramp(grade_frac=)` | `0.85` | ANCHORED | Build the ramp at 85 percent of the equipment limit, so it is drivable rather than marginal |
| `build_ramp(tolerance_m=)` | `0.15` | NUMERICAL | |
| ramp top percentile | `0.75` | ANCHORED, MEASURED trade | The 60th percentile leaves the road at mid-height; the 90th cuts so much of the pile into the road that the peak falls from 13.3 m to 11.1 m. Three quarters is where placement was best |
| `level(band_m=)` | `None` | ANCHORED, measured and rejected | Restricting the blade to a band near the working level dropped the peak from 13.6 m to 12.0 and broke three reclaim invariants. Left in the code, unused, with the result recorded |

### `reclaim`

| Name | Value | Class | Anchor |
|---|---|---|---|
| `LoaderSpec.dig_radius_m` | `15.0` | ANCHORED | Working envelope of the large hydraulic front shovel class. Declared in the docstring as a parameter of the run, not a fit |
| `LoaderSpec.max_cut_height_m` | `15.0` | ANCHORED | Same |
| `LoaderSpec.bucket_m3` | `34.0` | ANCHORED | Same |
| `LoaderSpec.payload_t` | `60.0` | ANCHORED | Same |
| `ReclaimFace.max_face_m` | `15.0` | ANCHORED | Safe working face height |
| `ReclaimFace.depth_m` | `5.0` | ANCHORED | How far into the pile one cut reaches |
| `ReclaimFace.width_m` | `30.0` | ANCHORED | Across-face extent of the face |
| tram stretch | `2 * dig_radius_m` | DERIVED | The stretch just worked |
| tram bound per cut | `max(2, ceil(width_m / (2 * dig_radius_m)))` | DERIVED | One sweep of the width. Unbounded assembly produced a 3303 m2 skim removing 0.31 m |
| `MAX_STANCES_TRIED` | `4096` | NUMERICAL | "generous enough never to bind on a real pad" |

### `material`

| Name | Value | Class | Anchor |
|---|---|---|---|
| `SWELL_HARD_ROCK` | `(0.30, 0.45)` | MEASURED band | "In hard rock operations, the percent swell is commonly between 30 and 45 percent" |
| `SWELL_ALL_MATERIALS` | `(0.10, 0.60)` | MEASURED band | Same source, wider band covering soils and weak rock |
| `COMPACTION_BAND` | `(0.05, 0.15)` | MEASURED band | "Typical compaction percentages range from 5 to 15 percent" |
| `PASSES_FOR_FULL_COMPACTION` | `25.0` | MEASURED band | Field trial quotes 20 to 30 passes on a 2 m layer |
| `Material.insitu_density_t_m3` | `2.70` | ANCHORED | Generic hard rock |
| `Material.swell` | `0.38` | ANCHORED | Middle of the hard-rock band |
| `Material.max_compaction` | `0.10` | ANCHORED | Middle of the compaction band |
| `Material.d50_mm` | `120.0` | ANCHORED | ROM feed |
| `Material.coarse_fraction` | `0.35` | ANCHORED | ROM feed |
| `Material.repose_dry_deg` | `37.0` | ANCHORED | Mid of the published ore range |
| `Material.repose_coarse_deg`, `repose_fine_deg` | `40.0`, `34.0` | ANCHORED | The DIFFERENCE is what drives stratification |
| `Material.moisture`, `saturation_moisture` | `0.03`, `0.20` | ANCHORED | 20 percent is the ingestion-contract flag for the dry-angle model going out of range |
| moisture curve gain, drop, floor | `+5.0` deg, `-8.0` deg, `0.66 * dry` | UNVERIFIED | Marked UNVERIFIED in the source itself. See below |
| `density_after_passes` time constant | `3 / 25` | DERIVED | `exp(-3)` is about 5 percent remaining at 25 passes |

### `blocks`, `sectors`, `blending`, `rtd`, `topography`

| Name | Value | Class | Anchor |
|---|---|---|---|
| `BlockModel.bulk_density_t_m3` | `1.9` | ANCHORED | Must match `TruckSpec.loose_density_t_m3` for tonnes to round-trip |
| `to_blocks(dz_m=)` | `5.0` | MEASURED | "a stockpile block model at 5 m blocks interpolated on 15 m centres" |
| `assert_consistent(tol_m=)` | `1e-6` | NUMERICAL | |
| `sectors._Z` | 1.6448536269514722, 1.959963984540054, 2.5758293035489004 | DERIVED | Two-sided normal quantiles at 0.90, 0.95, 0.99 |
| standard error denominator | `sqrt(n)` on the COUNT | DERIVED | Weights express how much material an observation speaks for, not how many measurements were made |
| `experimental_variogram(n_lags=)` | `20` | NUMERICAL | |
| `experimental_variogram` default `max_lag` | `span / 3` | ANCHORED | A conventional cut for a one-dimensional experimental variogram |
| `fit_spherical` grid | `40` steps, min 5 pairs per lag, min 4 lags | NUMERICAL | Grid search rather than a gradient method, deliberately, so the Python and TypeScript lanes give byte-identical results |
| `measured_range_t` threshold | 95 percent of series variance | ANCHORED | The usual practical-range convention |
| `measured_range_t(n_lags=)` | `30`, capped at `n // 2` | NUMERICAL | Unreliable on short streams at BOTH ends: it saturates at `max_lag * mean_tonnes` if the threshold is never reached, and interpolates below lag one if it is reached at the first lag. See guide 02 |
| `rtd.histogram(n_bins=)` | `24` | NUMERICAL | |
| `rtd.character` bands | `< 0.25` LIFO, `> 0.75` FIFO | ANCHORED | The docstring says outright there is no published threshold that makes 0.6 "mostly first-in-first-out", and the wording in a UI must say it is descriptive |
| topography shape exponents | sidehill `1.3`, valley `1.6`, ridge crest `1.6`, cross-valley `1.6` on the trough | ANCHORED | Shapes chosen for scenario clarity, not fitted to any landform |
| cross-valley amplitude split | trough `0.75 * relief_m`, along-valley fall `0.35 * relief_m` | ANCHORED | Coefficients, not exponents. They set how much of the relief is the drainage and how much is its own gradient |
| roughness octaves | 16 and 8 cells at amplitudes 1.0 and 0.5 | ANCHORED | Deliberately long wavelength: white noise of the same amplitude makes the trafficability mask read as static |

## The segregation cluster, in detail

This is where the anchoring bites hardest, because it is the only part of the engine whose OUTPUT is
not directly checkable against a survey.

### What is solved

Gray and Thornton's kinetic sieving, non-dimensionalised (their equation 3.18):

```
  dphi/dt + d(phi u)/dx + d(phi v)/dy + d(phi w)/dz - Sr * d/dz[ phi (1 - phi) ] = 0

    phi  volume fraction of the SMALL species, dimensionless, in [0, 1]
    u,v,w  bulk velocity components, non-dimensional
    Sr   the segregation number, dimensionless
```

On a stockpile flank the avalanche is a shallow layer of roughly uniform thickness flowing over a
static bed. Taking plug flow and marching in the downslope coordinate `x` reduces it to a
one-dimensional scalar conservation law in depth:

```
  dphi/dx + dF/dz = 0,        F(phi) = - Sr * phi * (1 - phi)

    x    non-dimensional downslope coordinate, 0 at the crest, 1 at the toe
    z    non-dimensional depth, 0 at the BASE of the layer, 1 at the free surface
```

`F` is convex, so a Godunov flux is exact for the Riemann problem at every interface, which is what
preserves the concentration shocks the source identifies as the physically observed feature. Gray and
Chugunov's diffusive remixing is added on the same interfaces:

```
  dphi/dx + dF/dz = d/dz( Dr * dphi/dz ),     Dr = Sr / Pe

    Dr   remixing diffusivity, dimensionless
    Pe   Peclet number, the ratio of sieving to remixing
```

The segregation number is the published ratio (equation 3.19):

```
  Sr = q * L / (H * U)

    q    mean segregation velocity, m/s
    L    path length down the face, m
    H    flowing-layer thickness, m
    U    typical bulk velocity, m/s
```

### Why the remixing term is not optional

Without it the pure hyperbolic flux separates the species completely and then stops. Measured directly
by marching one unit of downslope distance at several `Sr` and reading the base and surface fine
fractions:

```
  Pe = 12 (default)                     Pe = 0 (remixing off)
  Sr    base      surface               Sr    base      surface
  0.00  0.6500    0.6500                0.00  0.6500    0.6500
  0.20  0.9069    0.2866                0.20  0.9998    0.0012
  0.50  0.9720    0.1240                0.50  1.0000    0.0000
  1.00  0.9945    0.0445                1.00  1.0000    0.0000
  1.50  0.9981    0.0301                1.50  1.0000    0.0000
  4.00  0.9987    0.0273                4.00  1.0000    0.0000
 15.00  0.9987    0.0273               15.00  1.0000    0.0000
```

With remixing off, everything above `Sr = 0.5` gives the identical fully separated profile, so every
scenario in a product would report the same segregation whatever its drop height or face angle. Real
dumps sit between roughly `Sr = 1.8` and `Sr = 4`. Note that the remixing only postpones the
saturation: with `Pe = 12` the profile is still essentially frozen from `Sr = 4` upward. `PECLET_DEFAULT`
is therefore not just an accuracy parameter, it sets where the model stops responding, and a
calibration that moved it would move the whole upper half of the response curve.

Species mass is conserved exactly with the remixing on: `mean_phi` is `0.650000` before and after every
one of those marches.

### How `Sr` is obtained, and the two regimes

`avalanche_state` solves the layer from a depth-averaged momentum balance:

```
  a = g * (sin(t) - mu * cos(t))          acceleration on the slope, m/s2
  L = drop / sin(t)                       path length, m
  U = sqrt(2 * a * L)                     speed from rest at the crest, m/s
  H = max(Q / U, h_min)                   thickness from flux conservation, m
  q = kappa * (U / H) * d                 percolation velocity on the shear rate, m/s
  Sr = q * L / (H * U) = kappa * d * L / H^2

    t      face angle, radians
    mu     tan of the DYNAMIC friction angle = tan(repose_dry_deg - FLOW_HYSTERESIS_DEG)
    g      GRAVITY_M_S2 = 9.81 m/s2
    Q      CASCADE_FLUX_M2_S = 1.0 m2/s per unit width
    h_min  LAYER_MIN_DIAMETERS * d = 5 d, m
    d      d50_mm / 1000, m
    kappa  PERCOLATION_COEFFICIENT = 0.30
```

`U` cancels out of `Sr`. How fast the layer runs does not change how much it sieves per metre of
slope: a slower layer takes longer over the same path and sorts by the same amount.

Which branch of `max(Q/U, h_min)` binds decides the scaling entirely:

```
  flux-limited   H = Q/U      Sr = 2 * kappa * d * a * L^2 / Q^2   rises with drop AND with angle
  grain-limited  H = h_min    Sr = kappa * d * L / h_min^2         rises with drop, FALLS with angle
```

The grain-limited branch falls with angle because the thickness has stopped responding, so all that is
left of the angle is `L = drop / sin(t)`, which a steeper face shortens.

Measured crossover drop, the drop at which `Q/U` falls to `h_min`, for the default 120 mm material:

```
  face angle    crossover drop
   35 deg          1.9515 m
   37 deg          1.0244 m
   40 deg          0.6263 m
   45 deg          0.4038 m
```

And the resulting `Sr` surface:

```
  drop_m |     35 deg |     37 deg |     40 deg |     45 deg
    0.25 |     0.0056 |     0.0101 |     0.0155 |     0.0219
    0.50 |     0.0223 |     0.0406 |     0.0621 |     0.0707
    1.00 |     0.0893 |     0.1622 |     0.1556 |     0.1414
    1.02 |     0.0929 |     0.1688 |     0.1587 |     0.1442
    1.38 |     0.1701 |     0.2293 |     0.2147 |     0.1952
    2.00 |     0.3487 |     0.3323 |     0.3111 |     0.2828
    5.00 |     0.8717 |     0.8308 |     0.7779 |     0.7071
   11.00 |     1.9178 |     1.8278 |     1.7113 |     1.5556
   20.00 |     3.4869 |     3.3233 |     3.1114 |     2.8284
```

At a 0.5 m drop `Sr` rises with angle, which is the direction the sources report. At 11 m it falls,
because every one of those four is grain-limited and only the shortened run remains. The engine
straddles the crossover rather than sitting on one side of it.

**A recorded discrepancy.** The `facesegregation` module header quotes the 11 m row as
`1.928, 1.838, 1.721, 1.564`. Running the same call on the default material returns
`1.9178, 1.8278, 1.7113, 1.5556`, about half a percent lower at every angle. The 0.5 m row in that
docstring, `0.022, 0.041, 0.062, 0.071`, matches to the quoted precision. Prefer the computed values;
the docstring row appears to have been produced from a slightly different drop or angle and has not
been regenerated.

**How much of a real build is in each regime.** The module header states 42 percent flux-limited over
the 16762 loads that formed a face in the consuming product's scenarios, with a median drop of 1.38 m.
Measured independently on the quickstart build in [guide 01](01_install-and-quickstart.md), which is a
much smaller and shorter pile: of its 480 placed loads, 362 took a cascade profile and 240 of those
fell a non-zero drop, and those 240 split 120 flux-limited and 120
grain-limited, exactly 50 percent each, with a median drop of 1.022 m and a maximum of 7.597 m. Both
numbers are honest and they are different samples; what they agree on is that a real campaign sits ON
the crossover, so a calibration that only checks tall faces will validate the wrong branch. That is
precisely the error this release cycle corrected.

### The flow gate, and the trap in it

A face below the material's dynamic friction angle does not avalanche, so nothing sieves:

```
  flows  <=>  sin(t) - tan(radians(repose_dry_deg - FLOW_HYSTERESIS_DEG)) * cos(t) > 0
         <=>  face_angle_deg > repose_dry_deg - FLOW_HYSTERESIS_DEG
```

With the defaults that threshold is `37 - 4 = 33` degrees. Measured at a 5 m drop:

```
  face 32.000 deg -> flows False, sr 0.0000
  face 33.000 deg -> flows False, sr 0.0000
  face 33.001 deg -> flows True,  sr 0.0012
  face 34.000 deg -> flows True,  sr 0.8941
  face 37.000 deg -> flows True,  sr 0.8308
```

The jump from `sr 0.0012` at 33.001 degrees to `0.8941` at 34 is not a discontinuity in `Sr` itself,
it is `a = g(sin t - mu cos t)` passing through zero: `U` goes to zero, `H = Q/U` goes to infinity and
is caught by `h_min` almost immediately, so `Sr` climbs very steeply out of the gate and then settles
onto the grain-limited branch. The model is correct to say a slope at its own friction angle does not
run, and it is genuinely stiff within a degree of that angle. Do not calibrate anything in that band.

**The trap.** `Material.repose_dry_deg` and `build(repose_deg=)` are different arguments and the
engine never reconciles them. Setting the material's dry repose to 41 degrees while building at 37
silently switches ALL size segregation off, because `41 - 4 = 37` is not less than the face angle of
37. Measured on a small build with everything else held: the mean ledger coarse fraction went flat at
exactly the placed value `0.35` and the summed `sr` over all placed loads went to `0.0`, while the
placed count, the peak elevation and the ledger tonnage were bit-identical. Nothing raises, nothing
warns, and the pile looks right. If you change `Material.repose_dry_deg`, assert the gate:

```python
assert face_angle_deg > mat.repose_dry_deg - 4.0, "the face will not avalanche; nothing will sort"
```

### Sensitivity to `d50_mm`, which is non-monotonic

`h_min = 5 d`, so a coarser material has a thicker floor, and `Sr_grain = kappa d L / (5d)^2 = kappa L / (25 d)`
FALLS with `d`. In the flux-limited branch `Sr` RISES with `d`. Measured at 37 degrees:

```
  d50_mm | h_min_m | crossover@37 | Sr@1.02m | Sr@11m | regime@11m | on-face index@11m
      10 |   0.050 |    147.51 m  |   0.0141 |  1.636 | flux       | 0.3497
      25 |   0.125 |     23.60 m  |   0.0352 |  4.089 | flux       | 0.4373
      60 |   0.300 |      4.10 m  |   0.0844 |  3.656 | grain      | 0.4319
     120 |   0.600 |      1.02 m  |   0.1688 |  1.828 | grain      | 0.3661
     250 |   1.250 |      0.24 m  |   0.0814 |  0.877 | grain      | 0.2415
```

Sorting peaks around a 25 to 60 mm `d50` and falls off in both directions. A one-parameter sensitivity
run on `d50_mm` that sampled only 120 mm and 250 mm would conclude the relationship is monotonically
decreasing, and be wrong.

### What is imposed rather than solved, inside the solver

Two quantities in `segregate_face` are published operational observations, not results, and both are
kept separate from the sieving on purpose so each claim can be checked on its own.

**Where the mass lands down the face**, `w(s) = 0.35 + 0.65 s` normalised over the bins. This is the
statement that the cascade "aggregates more at the bottom of the dumping area under normal conditions
and less near the top crest", turned into the simplest ramp that reproduces it. It is a statement
about the cascade's geometry and not about sieving. The same ramp appears independently in
`dump._mass_shape` for the three cascading profiles, so the two modules carry a duplicated constant
that would have to be changed together.

**How much overruns the toe:**

```
  overrun = min(0.25, 0.30 * intensity * (1 - exp(-drop / 22.0)))    if the face flows, else 0

  intensity = h * a * s
     h = 1 - exp(-drop / 11.0)                            height term
     a = clamp((face_angle_deg - 28) / 12, 0, 1)          face-angle term
     s = 4 * c * (1 - c),  c = coarse_fraction            size-spread term
```

This is ballistic trajectory segregation, a mechanism the Gray-Thornton solver does not model at all.
Its MAGNITUDE is the anchored operational term above; its COMPOSITION comes from the solver, because
what overruns is whatever is still travelling in the layer at the toe.

**And the overrun is REPORTED, not REMOVED.** This is the most important caveat in the module and it
is easy to miss. Verified directly: `place_edge` puts the full requested volume on the pad regardless
of overrun, and nothing subtracts it afterwards.

```
segregate_face(10 m, 37 deg): overrun_fraction = 0.04466
place_edge added volume = 121.6 m3, asked for 121.6 m3
sum coarse_profile = 0.87269   sum fine_profile = 0.99985
mass balance: on face 0.955344 + overrun 0.044656 = 1.0
```

So the species bookkeeping balances to one, but the terrain receives 100 percent of the load. If you
need the material that rolled past the toe to actually sit on the floor in front of the pile, this
engine does not put it there.

### `intensity` is a driver, not a result

`intensity` combines the three published drivers and is exposed as `FaceSegregation.intensity`. It is
NOT the answer. `LoadRecord.segregation_index` used to be `intensity` and was changed, because
reporting a driver as though it were a result is how a field ends up meaning something different from
its name. The result is `segregation_index`, the difference in local coarse fraction between the toe
half and the crest half, computed from the profile the march produced. A negative value would mean the
model had been wired up backwards, so the sign is itself a test.

Measured over drops at 37 degrees in the default material:

```
  drop   sr      intensity  overrun  overrun_coarse  on-face index  total index
   0.50  0.0406  0.0303     0.0002   0.5439          0.0159         0.0169
   1.38  0.2293  0.0805     0.0015   0.8486          0.0880         0.0950
   5.00  0.8308  0.2493     0.0152   0.9832          0.2606         0.3002
  11.00  1.8278  0.4314     0.0509   0.9984          0.3661         0.4523
  20.00  3.3233  0.5717     0.1024   0.9995          0.3667         0.4988
```

Note the two indices diverging above about 11 m. That is not a defect: a taller face throws more
material clear of the toe, that material is almost pure coarse, and removing it from the face makes
the ON-FACE index stall while the load as a whole is more sorted. `total_segregation_index` counts the
overrun as toe material, which is the right answer to "did this dump segregate";
`segregation_index` is the right answer to "how sorted is the slope I am looking at". Report the one
you mean.

### What would replace these anchors

In priority order, and none of these has been run for this release.

1. **`PERCOLATION_COEFFICIENT`.** A DEM run of a bidisperse avalanche on a slope at the material's own
   angle, or the laboratory characterisation test, measuring the fines percolation velocity against
   the shear rate and the particle diameter. This is the one number the source calls out by name as
   the DEM calibration lane's target. It scales `Sr` linearly in both regimes, so it moves the whole
   response curve without changing its shape.
2. **`CASCADE_FLUX_M2_S`.** Video of a truck discharging over a crest, timing the body and measuring
   the crest length engaged. `Sr_flux` goes as `1/Q^2`, so this is the most leveraged number in the
   flux-limited half, and it also moves the crossover drop. It has no effect at all once the layer is
   grain-limited.
3. **`LAYER_MIN_DIAMETERS`.** The same DEM run, reading the flowing-layer thickness in particle
   diameters. `Sr_grain` goes as `1/h_min^2`, so a factor of two here is a factor of four in the
   grain-limited half.
4. **`PECLET_DEFAULT`.** Chute experiments on the actual material, fitting the shock thickness. This
   sets where the model saturates, so it matters most for tall faces.
5. **`FLOW_HYSTERESIS_DEG`.** A tilting-table start-stop measurement on the material. It matters
   disproportionately because it sets the flow gate, and near the gate the model is stiff.

## The trafficability cluster

`Fleet.max_grade = tan(radians(repose_deg)) / grade_limit_divisor`, with the divisor defaulting to
1.5. Both `terrain.Terrain.trafficable` and `truck.Fleet.of` state in their docstrings that this is a
commonly repeated operational rule of thumb and NOT a measured constant, and that the product must
describe it as a rule of thumb.

```
  divisor 1.00 -> max_grade 0.7536 = 37.00 deg
  divisor 1.25 -> max_grade 0.6028 = 31.08 deg
  divisor 1.50 -> max_grade 0.5024 = 26.67 deg   (default)
  divisor 2.00 -> max_grade 0.3768 = 20.65 deg
```

What would replace it: the equipment manufacturer's maximum sustained grade for the loaded machine on
the surface in question, which is a published figure for every haul truck class and is site-specific
because it depends on rolling resistance. Pass it directly as `grade_limit_divisor = tan(repose) / your_grade`,
or construct the `Fleet` and set `max_grade` yourself.

Three related choices sit alongside it:

- **`passable_mask` uses a CENTRAL DIFFERENCE, not the steepest neighbour drop.** This is a
  correctness decision documented with its measurement: using `Terrain.gradient`, which returns the
  worst drop in the 8-neighbourhood, marked the entire perimeter, the whole crest and the toe of every
  face as unstandable, and a clean 8 m platform with a correctly graded ramp came out with 30 of 1296
  cells reachable. Whether the NEXT cell can be reached is a separate question, asked per step by
  `step_ok`.
- **`reachable_mask` adds one fringe ring** of cells that are themselves too steep to stand on,
  because a truck spots AT the edge of a face and the crest cell it tips over is by definition steep
  on one side.
- **`solve_route(strict_goal=False)` exempts the goal cell from the gradient test.** Tipping over an
  edge and standing to be loaded are different manoeuvres and only the first justifies an unclimbable
  last step; `haul_cycle` passes `strict_goal=True` for exactly that reason. The source records
  honestly that on the current scenarios this changes no route, and that it is a correction of the
  semantics rather than the repair of an observed defect.

## The relaxation cluster

The toppling rule is Bak, Tang and Wiesenfeld's sandpile automaton, used purely as a mass-conserving
relaxation solver. None of the self-organized-criticality claims are made: the critical slope is
IMPOSED as the material's angle of repose rather than being a free parameter, and avalanche statistics
are out of scope.

A cell topples exactly to its repose surface in one step, by water-filling:

```
  d_k = z_c - z_k - drop_k        excess to over-steep neighbour k, m
  t_k = max(0, d_k - T)           what that neighbour receives
  T   = sum_k t_k                 total given away, solved as T = (sum of the k largest d) / (k + 1)

  drop_k = cell_m * tan(repose)            for an orthogonal neighbour
         = cell_m * sqrt(2) * tan(repose)  for a diagonal
```

`critical_drop(2.5, 37.0)` returns `(1.8838851252569855, 2.664215894091366)`. Using one drop for both
is what makes a relaxed cone come out square.

Two stages, and this is measured physics rather than numerics: material is emplaced at the fresh-heap
slope and slumps to repose afterwards. `settle()` runs the cascade at `FRESH_HEAP_DEG = 63.43` degrees
first and at the material angle second, which also produces two distinct avalanche paths.

### `STABLE_TOL_DEG = 4.0`

The verifier allows a pair to stand four degrees over the imposed angle before raising
`ReposeViolation`. The source states both requirements it was set from, and neither is "what made a
build pass": it must catch the defect the invariant exists for (the predecessor engine finished with
446 over-steep pairs, the worst at 55.9 degrees against an imposed 37, an overshoot of 18.9, so four
degrees leaves a factor of nearly five in hand), and it must not flag residue that is small against
the uncertainty in the angle itself (published handbook values for ores span 34 to 60 degrees, so four
degrees is a sixth of that spread).

What it actually costs, measured across the consuming product's shipped matrix: nineteen of twenty-one
scenarios relax to ZERO pairs over the STRICT angle and use none of the tolerance. Two sloping cases
do not, a sidehill leaving four pairs at 40.5 degrees and a ridge crest leaving two at 39.2, in both
cases after the sweeps stopped making progress and a reseed on the offenders failed to move them.

Independently confirmed on the quickstart build, which is flat ground:

```
final surface at the STRICT 37 deg: 0 over-steep pairs, worst 37.000 deg
max_slope_excess: 1.99467e-09 m
```

The residual is two nanometres. Report `count_over_repose` at the STRICT angle in any manifest, so the
residue is visible rather than hidden behind the tolerance.

### `BARE_M = 1e-3`

A cell carrying less than a millimetre of material is exempt from the repose check. The angle of
repose is a property of loose material, not of bedrock: a natural hillside is entitled to stand
steeper than any ore will, and flagging it would make the invariant meaningless on four of the five
published fill types. The threshold used to be the verification tolerance, a micrometre, and a cell
holding a millimetre of dust was therefore asked to stand at an angle of repose it cannot reach,
because shedding everything it has leaves the ground and the ground is where it already is. Measured
on a sidehill and a ridge, that produced violations reported at 37.0 and 37.1 degrees against an
imposed 37: the solver being correct and the check being wrong.

## The material moisture curve is UNVERIFIED, and the source says so

```
  w <= 0                     repose = repose_dry_deg
  w >= saturation_moisture   repose = 0.66 * repose_dry_deg
  otherwise:
      peak = saturation_moisture / 3
      gain = 5.0 * sin(pi * min(w / saturation_moisture, 1))
      drop = 0 if w <= peak else (w - peak) / (saturation_moisture - peak) * 8.0
      repose = max(repose_dry_deg + gain - drop, 0.66 * repose_dry_deg)
```

Evaluated on the default material:

```
  moisture 0.0000 -> 37.000 deg
  moisture 0.0200 -> 38.545 deg
  moisture 0.0300 -> 39.270 deg   (the default moisture)
  moisture 0.0500 -> 40.536 deg
  moisture 0.0667 -> 41.329 deg   (the peak, at saturation/3)
  moisture 0.1000 -> 40.000 deg
  moisture 0.1500 -> 35.536 deg
  moisture 0.2000 -> 24.420 deg   (saturated: 0.66 * 37)
  moisture 0.3000 -> 24.420 deg
```

The docstring is explicit: "The shape is a published qualitative relationship rather than a fitted
curve, and the product must say so. What is defensible is the direction and the existence of a peak,
not the exact value at any given moisture. UNVERIFIED as a quantitative model." The `+5.0` gain, the
`-8.0` drop and the `0.66` saturated floor are all invented magnitudes for a real shape.

What would replace it: a direct-shear or tilting-box series on the actual material across a moisture
range, which is a routine geotechnical test. It is also the lowest-value calibration in this list,
because as guide 02 documents, **`Material.repose_deg()` is not called anywhere in the engine.** The
build path takes its angle from the `repose_deg` argument. This curve is a caller-facing utility, and
until something wires it in, calibrating it changes nothing.

## What the engine does not model, at all

This list is exhaustive as far as reading the source can make it. Each item is a real omission, not a
simplification of something present.

**Granular mechanics.**

- The angle of repose is IMPOSED, not emergent. This is a continuum height-field model, not DEM. It
  reproduces the geometry a given repose angle produces; it cannot predict that angle from particle
  properties, and `Material.repose_dry_deg` only reaches the geometry if the caller passes the same
  number to `build`.
- Trajectory segregation is not modelled. Only kinetic sieving is. What rolls beyond the toe is
  reported as an overrun magnitude from an anchored operational term, with a solver-derived
  composition, and it is NOT removed from the placed volume.
- Size is TWO SPECIES, coarse and fine. Not a particle-size distribution. A full PSD would be a
  different model and a much larger claim, and every measured statement the module is built on is
  binary.
- Particle breakage, degradation and attrition do not exist. `d50_mm` is constant from the shovel to
  the plant.
- Compaction under traffic is computable via `Material.density_after_passes` and is never applied. The
  ledger uses one bulk density everywhere.
- Moisture, drainage, rainfall, freezing and dust are absent. `Material.moisture` reaches nothing.
- Cohesion, cementation and ageing are absent. A pile does not consolidate over time.
- There is no stability analysis of any kind. No factor of safety, no slope failure, no liquefaction,
  no foundation bearing capacity. The relaxation guarantees a surface at or below repose and says
  nothing about whether the mass is safe.

**Chemistry, geometallurgy and the plant.**

- ONE grade scalar per load. No multi-element assays, no deleterious elements, no recovery model, no
  hardness or throughput index.
- No blending optimizer. The engine EVALUATES a pile; it does not choose one, sequence one, or
  recommend a reclaim order.
- No plant metal accounting. It stops at the reclaimed stream. There is no crusher, no mill and no
  mass balance beyond the pile.
- No oxidation, no leaching, no self-heating, no acid generation, no time-dependent chemistry of any
  kind. Residence time is computed; nothing depends on it.

**Fleet and operations.**

- No fleet scheduling. One truck is routed per load and one per cut. There is no queue, no cycle time,
  no spot time, no bunching, no dispatch optimisation. `CycleState` has queue states and nothing
  advances a clock through them.
- There is no clock at all. The engine has no time coordinate. `LoadRecord.seq` is an ordinal, and
  `rtd` takes times as caller-supplied arrays that the engine never generates.
- No equipment availability, no breakdowns, no shift patterns, no operator behaviour beyond the
  spotting rule.
- No cost, no fuel, no productivity and no economics.
- One dozer per area, implicit, with no position and no travel. `_doze` is an instantaneous set of
  transfers, not a machine on the pad.

**Geometry and representation.**

- `Area` is an AXIS-ALIGNED RECTANGLE. Real dump-location polygons are general polygons; this is
  stated as a known simplification in `design.Area`.
- The pad is a regular grid with one cell size, no rotation, no origin offset and no coordinate
  reference system. There is no nodata sentinel.
- The pad edge is a WALL. Material reaching the boundary stays on the pad rather than falling off it,
  which keeps mass conservation exact and means a pile that touches the boundary is being modelled
  wrongly. Nothing raises; the caller has to check.
- Elevation is a single-valued height field, so overhangs, undercuts, voids and re-entrants cannot
  exist.
- No sub-surface: no foundation, no water table, no basal drainage layer, no liner.

**Uncertainty.**

- `grade_uncertainty` is CARRIED, never used. It is weighted and reported and it never perturbs a
  grade or widens a result. There is no Monte Carlo, no ensemble, no conditional simulation and no
  propagation of uncertainty through the build.
- `displacement_m` is likewise a reported statistic. Nothing degrades a provenance claim in proportion
  to it; the caller has to decide what a 69 m mean displacement means for a provenance fraction.
- `Rollup.ci` is a normal-theory interval on a mean, using the COUNT of observations as the
  denominator. It is not a geostatistical uncertainty and it does not account for spatial correlation
  between the columns it aggregates.

**Reclaim.**

- Only three extraction orders, and they are ORDERS, not machine geometries: LIFO, FIFO, full-height.
  There is no bucket-wheel, no bridge reclaimer, no drum, no apron feeder and no reclaim tunnel,
  because those are conveyor-stacked bed equipment and this engine is deliberately about truck-built
  piles.
- Nothing rehandles. A cut leaves the ledger and leaves the model.
- The loader is a stance, a reach and a lift height. It has no cycle time, no swing, no bucket fill
  factor and no position between stances.

**And the category the whole package refuses.**

- Chevron, windrow, cone-shell, chevcon and strata beds. Those are built by CONVEYOR STACKERS, and of
  the five pre-crusher stockpile types only blended-in-blended-out is a chevron. Trucks do not build a
  chevron bed. An earlier version of this library offered those geometries alongside a truck fleet and
  `tests/test_readme.py` now fails the build if the front page starts offering them again.

## A calibration campaign, in priority order

If you can run one measurement, run the first. If you can run five, run the first five.

1. **`PERCOLATION_COEFFICIENT`** by DEM or laboratory characterisation. It scales the entire
   segregation response and is the number the source names as the calibration lane's target.
2. **The truck gradient limit**, replacing `grade_limit_divisor = 1.5` with the manufacturer's
   sustained-grade figure for your machine on your surface. It changes the refusal rate, which changes
   the pile, which changes everything downstream. It is also the cheapest measurement on this list.
3. **`CASCADE_FLUX_M2_S`** by timing a discharge. It moves the crossover drop, which decides which
   branch your loads are on.
4. **`Material.coarse_fraction` and `d50_mm`** from a sieve analysis of your ROM feed. Both are read
   by the build path, both move the answer a long way, and `d50_mm` is non-monotonic so a two-point
   sensitivity is not enough.
5. **`LAYER_MIN_DIAMETERS`** from the same DEM run as (1).
6. **The bulk density**, set consistently on `TruckSpec.loose_density_t_m3` AND
   `BlockModel.bulk_density_t_m3`. It does not change any geometry, but it changes every tonnage and
   therefore every tonnage-weighted statistic.
7. **`PROFILE_STATS`**, if you have your own UAV survey of dumps. These are the only MEASURED numbers
   in the segregation and deposition path, and replacing a 28-dump study from one site with your own is
   a straightforward substitution: the dictionary is the whole interface.
8. **`lift_thickness_m`, `loads_per_dozer_pass` and `paddock_frac`** from your own dozer practice.
   These are operational rather than physical and your operation already knows them.
9. **`PECLET_DEFAULT` and `FLOW_HYSTERESIS_DEG`** by chute and tilting-table work. Lowest value per
   unit of effort, but they are what would let the model be trusted on tall faces and near the flow
   gate.

Whatever you calibrate, record it next to the result. The whole point of this document is that a
number nobody can trace is worse than a number nobody has measured.

## References cited in this guide

Only sources the repository itself cites, in a module docstring or in the README reference list. No
citation here was added by this guide.

- Gray, J.M.N.T. and Thornton, A.R. (2005), *A theory for particle size segregation in shallow
  granular free-surface flows*, Proc. R. Soc. A 461(2057), 1447-1473.
  [doi:10.1098/rspa.2004.1420](https://doi.org/10.1098/rspa.2004.1420)
- Gray, J.M.N.T. and Chugunov, V.A. (2006), *Particle-size segregation and diffusive remixing in
  shallow granular avalanches*, J. Fluid Mech. 569, 365-398.
  [doi:10.1017/S0022112006002977](https://doi.org/10.1017/S0022112006002977). A second recorded
  discrepancy, of the same kind as the 11 m row above: the comment carrying this DOI in
  `bedblend/segregation.py` repeats the 2005 paper's title for it. The title given here is the one
  the README's reference list carries for the same DOI, and it is the correct one.
- Young, A. and Rogers, W.P. (2021), *Modelling of pre-crusher stockpiles*, Minerals 11(6), 636.
  [doi:10.3390/min11060636](https://doi.org/10.3390/min11060636)
- Young, A. and Rogers, W.P. (2022), Mining 2(1).
  [doi:10.3390/mining2010006](https://doi.org/10.3390/mining2010006). The 28 UAV-surveyed dumps behind
  `PROFILE_STATS` and the `MEASURED_*` envelopes.
- Bak, P., Tang, C. and Wiesenfeld, K. (1987), *Self-organized criticality: an explanation of 1/f
  noise*, Phys. Rev. Lett. 59, 381.
  [doi:10.1103/PhysRevLett.59.381](https://doi.org/10.1103/PhysRevLett.59.381). The toppling rule
  only; none of the criticality claims are made.
- Loubser, R. and de Korte, G.J. (2015), J. S. Afr. Inst. Min. Metall. 115(8), 773-780.
  [doi:10.17159/2411-9717/2015/v115n8a15](https://doi.org/10.17159/2411-9717/2015/v115n8a15)
- Moraga, Kracht and Ortiz (2022), Minerals Engineering 187, 107807.
  [doi:10.1016/j.mineng.2022.107807](https://doi.org/10.1016/j.mineng.2022.107807). Process-scale RTD.
- Cogent Engineering 4(1), 1387955.
  [doi:10.1080/23311916.2017.1387955](https://doi.org/10.1080/23311916.2017.1387955)
- Neufeld, C., Lyall, G. and Deutsch, C.V. (2006), CCG Report 8, paper 306. No DOI in the source.
- Schramm, AT MINERALS PROCESSING 06/2021. The mixing-effect anchor of `E` 5 to 7.5 at 200 to 600
  layers. No DOI in the source.
- Baffinland, *Life-of-Mine Waste Rock Management Plan* (2017). The dozer's role in deciding traffic.
  No DOI in the source.
- Atlantech open-cut mining swell figures, consistent with the NRC bulking-factor compilation
  ML080700314. The swell bands. No DOI in the source.
- Micromine Alastri APS stockpile documentation. The FIFO, LIFO and blended reclaim abstraction. No
  DOI in the source.
- De Wet (1994), Bulk Solids Handling 14(1) p. 93. Cited here ONLY to record that `blending.py` states
  it could not be verified, is not available online, and is therefore deliberately NOT reproduced or
  attributed in the code. The `1/N` bound the engine implements is derived from first principles and
  labelled as derived.
