# 04. Relaxation: holding the angle of repose

Source: `bedblend/relax.py`. Public API: `critical_drop`, `neighbour_table`, `cascade`,
`max_slope_excess`, `count_over_repose`, `relax_to`, `settle`, `assert_stable`, `ReposeViolation`,
`FRESH_HEAP_SLOPE`, `FRESH_HEAP_DEG`. `cells_over_repose`, `MAX_MOVES`, `CONVERGE_TOL_M`,
`VERIFY_TOL_M`, `BARE_M` and `STABLE_TOL_DEG` are module-level but are not re-exported from the
package root; import them from `bedblend.relax` when you need them.

This module takes an elevation field that has just been made too steep, by a dump, a dozer pass or a
reclaim cut, and moves material downhill until no local slope exceeds a given angle, conserving mass
exactly and returning the transfers in the order they happened. It is the second half of every
material-moving operation in the engine. The first half, placement, is
[03. Placement and profiles](03_placement-and-profiles.md).

## The solver is a Bak-Tang-Wiesenfeld toppling rule, and that is all it is

The local rule is the one Bak, Tang and Wiesenfeld introduced for the sandpile automaton: a site whose
height difference to a neighbour exceeds a critical value is unstable and sheds material to that
neighbour, which may in turn destabilise its own neighbours, and the update cascades.

Bak, P., Tang, C. and Wiesenfeld, K. (1987). *Self-organized criticality: an explanation of the 1/f
noise*. Physical Review Letters 59(4), 381-384.
[doi:10.1103/PhysRevLett.59.381](https://doi.org/10.1103/PhysRevLett.59.381). This is the DOI the
module docstring carries, and it is the only citation in the module.

**None of the self-organized-criticality claims are made here, and this distinction is the reason the
paragraph exists.** In the BTW model the critical slope is what the system organises itself toward,
and the object of study is the avalanche size distribution, its power law and its 1/f spectrum. In
this module the critical slope is IMPOSED as the material's angle of repose, and avalanche statistics
are out of scope: nothing counts avalanche sizes, nothing fits an exponent, and no criticality is
claimed, tested or needed. The toppling rule is used purely as a mass-conserving relaxation solver.

Where that angle comes from is worth stating precisely, because it is not where a reader would guess.
`relax.py` never touches `Material`. Every entry point takes a bare `repose_deg: float`, and `build`
takes its own `repose_deg` parameter defaulting to 37.0 and passes that through to `settle`,
`relax_to` and `_doze`. `Material.repose_deg(moisture=...)` exists and implements the moisture curve,
but nothing in the engine calls it; the only callers are in `tests/test_material_segregation.py`. So
the moisture dependence of repose is modelled and available, and the build does not use it.

The implementation also differs from the BTW automaton in ways a reader should not have to discover
from the code:

* BTW is integer-valued with a fixed toppling quantum. Here heights are continuous floats and the
  transfer is computed exactly, so a cell reaches its repose surface in one topple rather than in many
  quantised steps.
* BTW topples to 4 neighbours on a square lattice with one threshold. Here there are 8 neighbours and
  TWO thresholds, because the diagonal run is longer by the square root of 2.
* BTW's canonical update is parallel over all unstable sites. Here the update is sequential in a
  priority order, highest cell first, for reasons measured and recorded below.
* BTW has no floor. Here the transfer out of a cell is capped by the material available above the
  original ground.

## The stability criterion

```
critical_drop(cell_m, repose_deg) -> (orth, diag)

    orth = cell_m * tan(radians(repose_deg))          maximum stable drop to an orthogonal neighbour
    diag = orth * sqrt(2)                             maximum stable drop to a diagonal neighbour
```

An ordered pair of cells `(c, n)` is stable when

```
z[c] - z[n] <= d(c, n)
```

where `d(c, n)` is `orth` for the four orthogonal neighbours and `diag` for the four diagonal ones.
The repose angle is a slope, so the admissible drop scales with the horizontal distance between cell
centres. Using one drop for both is the mistake that makes a relaxed cone come out square; the
docstring names it explicitly.

At the engine's usual settings, 2.5 m cells and 37 degrees:

```
cell_m   repose_deg    orth        diag        diag/orth
   2.5      37.000    1.883885 m  2.664216 m    1.414214
   2.5      63.435    5.000000 m  7.071068 m    1.414214
   1.0      37.000    0.753554 m  1.065686 m    1.414214
   2.5      45.000    2.500000 m  3.535534 m    1.414214
```

`neighbour_table(nx, ny, cell_m, repose_deg)` precomputes the `(neighbour_index, admissible_drop)`
pairs for every cell and caches them per pad geometry. Building this inside the relaxation loop was
the single largest cost in the engine, per the docstring: a cascade sweeps thousands of cells, and
allocating a fresh eight-element list for each of them on every sweep of every load dominated
everything the science was doing. Corner cells get 3 entries, edge cells 5, interior cells 8. The
pad edge is a WALL: material reaching the boundary stays on the pad rather than falling off it, which
is what keeps mass conservation exact. A pile that touches the boundary is a scenario problem for the
caller to flag, not tonnes to lose quietly.

The cache is bounded by a clear-all rather than an eviction policy. Measured: it grows to 17 entries,
then the next distinct geometry clears it and leaves 1. The comment's rationale is that a session
sweeps few geometries and the dictionary should not grow without bound.

## How a cell topples: the water-filling transfer

A cell gives away a total `T`, split over its over-steep neighbours so that every constraint is
satisfied simultaneously and none is overshot.

```
for each neighbour n_k of cell c:
    e_k = z[c] - z[n_k] - d_k              the excess over the admissible drop, metres
    keep only the neighbours with e_k > CONVERGE_TOL_M

find T solving      T = sum_k max(0, e_k - T)
then transfer       t_k = max(0, e_k - T)   to each neighbour k
```

Sorting the excesses in decreasing order, the solution for the `k` largest is closed form:

```
T = (e_1 + e_2 + ... + e_k) / (k + 1)
```

and the code finds the right `k` by accumulating and stopping at the first `k` where
`e_k <= (e_1 + ... + e_k) / (k + 1)`. Over 20000 random draws of 1 to 8 excesses, the level the code
selects satisfies the fixed-point equation `T = sum_k max(0, e_k - T)` in every single case, to within
1e-12.

The transfer lands each fed pair exactly on its repose surface. After the topple the drop from `c` to
`n_k` is

```
(z[c] - T) - (z[n_k] + e_k - T)  =  z[c] - z[n_k] - e_k  =  d_k
```

which is the admissible drop, exactly, independent of `T`. This is what "toppling exactly to its
repose surface, in one step" means, and it is the property the floor can break, below.

### Why a priority cascade and not sweeps

The heap holds `(-height, cell)` and is popped highest-first, with lazy invalidation: a stale entry is
recognised because the cell is no longer unstable, and is dropped. The docstring records what
motivated this: simultaneous sweeps let a cell receive from several neighbours at once and overshoot
above the neighbour it had just fed, so the pair traded material back and forth, and a cone that
should relax in about eight steps took over a hundred sweeps. That is a measurement of the previous
implementation, recorded in the source; this document did not re-run it.

Three re-queue rules follow every topple, and the third is the one that fixed the defect this module
was rewritten for:

1. Every neighbour that RECEIVED material is pushed, since it grew and may now be over-steep against
   its own downhill neighbours.
2. The cell is re-queued only after real progress, meaning at least one transfer larger than
   `CONVERGE_TOL_M` actually moved. Every candidate transfer can come out at or below tolerance while
   the cell still reads as marginally unstable, and re-queueing then would spin forever because
   nothing moves and the loop's only bound is on the number of moves.
3. Every neighbour that now stands ABOVE the toppled cell is re-queued, because the cell that gave
   material away got lower and that destabilises the cells above it. The docstring records the failure
   this fixes: a highest-first queue processes an uphill neighbour before this cell, finds it stable,
   and never looks at it again; then this cell drops, the drop from that neighbour down to here grows
   past repose, and nothing re-queues it. The original solver pushed only the receivers and the
   toppling cell, so those pairs survived to the end of the run: 446 of them on a measured case, the
   worst at 55.9 degrees against an imposed 37.

### Termination

Rule 2 above is what makes the argument work. A transfer of `t` from `c` to `n` with drop
`D = z[c] - z[n]` changes the sum of squared heights by

```
(z[c] - t)^2 + (z[n] + t)^2 - z[c]^2 - z[n]^2  =  2t(t - D)
```

which is strictly negative whenever `0 < t < D`. Both hold: `t` is at least `CONVERGE_TOL_M` by rule
2, and `t <= e = D - d < D` because the admissible drop `d` is strictly positive for any repose angle
above zero. So the sum of squared heights strictly decreases with every re-queueing transfer, and it
is bounded below. Measured on a 30 m spike relaxing to 37 degrees on a flat 40 by 40 pad at 2.5 m
cells: 261 transfers, sum of squares from 900.0 to 72.9723, total height 29.999999999999993 against
the 30.0 placed. That last figure is the honest one. Each individual transfer is exact, but summing
261 of them back out of a 1600-element list is not, so mass conservation here means conserved to
7e-15 m of column height, not to the bit.

`MAX_MOVES = 2_000_000` is a hard backstop on the number of transfers, not the expected exit. A
converged cascade uses a tiny fraction of it. If you see a cascade returning exactly 2000000 moves,
something is wrong; the one case in this document that hits the cap is the `respect_ground=False`
misuse described later.

### Does the seed set change the answer

For a single 30 m spike on a flat pad, no. Seeding on the spike alone, seeding on the whole pad, and
seeding on the spike plus one distant irrelevant cell all produce 261 transfers, the identical move
sequence, and final surfaces that agree to 0.0 m. This is a measurement on one symmetric case and is
not a proof of order independence in general; the two-stage result below shows that changing the
SEQUENCE OF IMPOSED ANGLES definitely does change the final surface.

`_expand_seeds` grows any supplied seed set by one ring before the cascade starts. A deposit writes a
set of cells, but the cells it destabilises can include neighbours it never touched, since a cell
exactly at repose becomes over-steep the moment the cell beside it grows. Seeding only the written
cells is how a relaxation comes back reporting success while leaving permanent over-steep pairs
behind.

## The two stages: a fresh heap does not appear at the angle of repose

This is a physical finding, not a numerical convenience. Quoted in the docstring from Minerals 2021,
figure 11: "At the time of dumping, heaps maintain an approximate 2:1 slope, consistent with that of
heaped loaded material. Over time the slope decreases to that of the natural angle of repose of the
material."

```
FRESH_HEAP_SLOPE = 2.0                                    rise over run
FRESH_HEAP_DEG   = degrees(atan(FRESH_HEAP_SLOPE))
                 = 63.43494882292201                      degrees
```

63.4 degrees is well above any ore's repose angle, which is why `relax_to` takes a target angle as an
argument and `settle` runs the sequence:

```python
settle(terrain, repose_deg, *, active=None, fresh_deg=FRESH_HEAP_DEG) -> list[(src, dst, metres)]
```

```
stage 1   cascade at fresh_deg (63.435 by default), seeded on `active`, floor = terrain.z0
stage 2   cascade at repose_deg, seeded on `active` plus every cell stage 1 touched
stage 3   only if count_over_repose is non-zero: an unseeded whole-pad cascade at repose_deg
always    assert_stable(terrain, repose_deg), whether or not stage 3 ran
```

Two details the pseudocode above compresses. `assert_stable` is NOT part of stage 3: it is called
unconditionally on the way out, so a `settle` that converged in stage 2 is still verified, and there
is no argument that turns it off. And the stage-2 seed set is only "`active` plus what stage 1
touched" when `active` was given at all; when `active is None` the seed is left as `None`, which means
the whole pad, because a caller who did not say what changed has not earned a cheap seed.

The stage-2 seed set is the deliberate middle path between two wrong options. It cannot be the deposit
alone, because stage 1 has already moved material outward and cells that were never written can now be
over-steep. It must not fall back to the whole pad either: doing that costs a full-pad heapify on
EVERY load, which the docstring records as the dominant cost of a build and as what made an end-to-end
run unusable. The correct seed is the deposit plus every cell stage 1 touched, since a cell that
neither received material nor had a neighbour change cannot have become unstable.

### What the two stages actually do, measured

For a SINGLE default load, stage one does nothing at all, and a maintainer should know this before
attributing behaviour to it. One CAT 793F load of 121.5789 m3 placed by `place_paddock` on a flat 2.5 m
pad peaks at 3.1509 m over 8 cells with a maximum local slope of 51.571 degrees. That is below 63.435,
so stage one performs zero transfers and the whole slump happens in stage two: 4 transfers, peak down
to 2.5174 m, footprint out to 12 cells, mass unchanged at 121.578947 m3 exactly. On this case
`settle(t, 37)` and `relax_to(t, 37)` produce bit-identical surfaces.

The two-stage path becomes distinguishable when the local slope actually exceeds 63.435 degrees. Six
loads stacked on one spot peak at 18.9056 m with a maximum local slope of 82.47 degrees. Then:

```
                              transfers   final peak   max local slope after
stage 1 alone at 63.435 deg          81     10.7594 m           63.43 deg
settle to 37 (both stages)         1789      5.9801 m           37.00 deg
relax_to 37 (one stage)            2566      6.0121 m           37.00 deg
```

The two final surfaces differ by up to 0.5295 m, and both conserve the placed 729.473684 m3 exactly.
So the claim in the docstring that "the two calls also produce two distinct avalanche paths, and
segregation acting along both is not the same as segregation acting along one" is correct in the sense
that the paths and the resulting surface genuinely differ. Be careful with the second half of that
sentence, though: see the note on what consumes the move list, below.

## The floor: `respect_ground`

```python
relax_to(terrain, repose_deg, *, active=None, verify=True, respect_ground=True)
```

With `respect_ground=True`, the default, the cascade is given `floor = terrain.z0`, the ORIGINAL
ground, and a cell can only shed the material sitting above it:

```
budget = z[c] - floor[c]                  metres available to give away
t_k    = min(t_k, budget)                 each transfer is capped, and the budget is spent in order
```

Two things follow. Mass is still conserved, to summation noise rather than to the bit (4.7e-13 m3 on
the case measured below), but a capped transfer no longer lands the pair on its repose surface, so a
cell fed by a truncated transfer can be left marginally over the angle without ever having been
queued. That is the mechanism behind the re-sweep loop in the next section.

The reference case for the rest of this section is a planar bedrock hillside falling at 45 degrees in
+x across a 40 by 40 pad at 2.5 m cells, with `z0 == z`, so every cell is bare rock. On that ground
`count_over_repose(..., floor=z0)` returns `(0, 0.0)` because every cell is skipped as bare, while
the same call with `floor=None` returns 1560 pairs at 45.00 degrees: one orthogonal pair per cell that
has a downhill orthogonal neighbour. The diagonals do not count at 45 degrees, since a 2.5 m drop over
a 3.5355 m diagonal run is 35.3 degrees, inside repose. Placing one default 121.5789 m3 load on that
hillside and calling `relax_to(t, 37)` gives 18828 transfers, mass conserved to 4.7e-13 m3, a minimum
thickness of exactly 0.0 m, meaning no cell was driven below its original ground, and 0 floor-aware
pairs left with a worst residual of 37.00000004851246 degrees.

**`respect_ground=False` is only meaningful on ground that is itself at or below the repose angle.**
On that same hillside and that same single load, `relax_to(..., respect_ground=False, verify=False)`
returns 16000000 transfers, eight full cascades each hitting `MAX_MOVES`, takes about 140 seconds,
cuts 2.3452 m into the bedrock, and still leaves 151 floor-aware pairs with the worst at 61.8 degrees.
With `verify=True` the same call raises `ReposeViolation` reporting 127 pairs and a worst local slope
of 61.8 degrees. The two counts differ because `assert_stable` checks at `repose_deg + STABLE_TOL_DEG`,
41 degrees, while the floor-aware count above was taken at the strict 37. It fails loudly rather than
quietly, which is the right behaviour, but it wastes a great deal of time doing so.

Note the asymmetry: `relax_to` honours `respect_ground` when solving, but the `assert_stable` it calls
at the end always verifies with `floor=terrain.z0`. That direction is safe, because a floor-aware
check is the more permissive one and cannot invent a failure, but it does mean a
`respect_ground=False` run verifies a weaker condition than the one it solved.

## Two floor-aware exemptions in the verifier, and why each exists

`count_over_repose(z, nx, ny, cell_m, repose_deg, *, floor=None)` returns
`(number of over-steep ordered pairs, worst local slope in degrees)` and applies two skips when a
floor is given.

**A bare cell is skipped entirely.**

```
BARE_M = 1e-3        metres; below this a cell is carrying no material worth the name
if floor is not None and z[c] - floor[c] <= BARE_M:  skip cell c
```

The angle of repose is a property of loose material, not of bedrock. A natural hillside is entitled to
stand steeper than any ore will, and flagging it would make the invariant meaningless on four of the
five published fill types. The threshold used to be the verification tolerance, a micrometre, and the
docstring records what that produced: a cell holding a millimetre of dust was asked to stand at an
angle of repose, which it cannot, since shedding everything it has leaves the ground and the ground is
where it already is. Measured on a sidehill and a ridge, that produced violations reported at 37.0 and
37.1 degrees against an imposed 37, the solver being correct and the check being wrong.

Reproduced in isolation on a 2 by 2 pad at 2.5 m cells, the left column high and the right column at
zero, so there are two ordered pairs to find. At 37 degrees the admissible orthogonal drop is
1.883885 m. Set the ground drop to 1.883485 m, just under the limit, and add a skin of material on
each of the two upper cells:

```
skin      actual drop     counted pairs   worst reported
0.8 mm    1.884285 m            0          0.0000 deg      skipped, thickness <= BARE_M
2.0 mm    1.885485 m            2         37.0234 deg      counted, thickness > BARE_M
```

The pair count tracks the pad: on a 2 by 1 pad the same two skins give 0 and 1. What matters is the
threshold, not the count.

**A pair whose steepness is INHERITED is skipped.**

```
if floor is not None and (floor[c] - z[n]) - run * slope >= -VERIFY_TOL_M:  skip this pair
```

Skipping bare cells is not enough. A cell carrying a thin skin over ground that already stands steep
would be flagged, and nothing can clear it: shedding every grain it has leaves the ground, and the
ground is still over the angle. The cascade knows this and correctly declines to move anything; the
check did not, so the two disagreed and a build died on a surface that was as relaxed as it can
physically be. The docstring records the measurement: on a sidehill, 65 pairs with the worst at 49.1
degrees, every one of them inherited. The test written into the code is whether removing the material
would fix it, and the escape allows equality, because if shedding every grain would still leave the
cell at or over the angle then the steepness is the ground's and no solver can take it away.

Two consequences of these skips that are easy to trip over:

* `worst_deg` is computed only over non-bare cells, so on an entirely bare pad it returns 0.0. That
  means "nothing to report", not "flat".
* `max_slope_excess` has NO floor parameter and applies neither skip. On the bare 45-degree bedrock
  hillside defined above it returns an excess of 0.6161 m, which is just `2.5 - 1.883885`, while
  `count_over_repose` with the floor returns `(0, 0.0)` on the same field. Use `count_over_repose` as
  the invariant on any ground that is not flat;
  `max_slope_excess` is a raw diagnostic on the field, useful for judging convergence on a flat pad
  and misleading anywhere else.

## Two tolerances, and why the verifier's is looser than the solver's

```
CONVERGE_TOL_M = 1e-9      what the solver settles each pair to
VERIFY_TOL_M   = 1e-6      what the verifier allows
```

A cascade settles each pair to within `CONVERGE_TOL_M`, but a cell is touched by many transfers and
the rounding accumulates, so a converged field can sit a few nanometres over the line. Checking at the
solver's own tolerance would flag that as a failure, which would make the invariant cry wolf and train
a reader to ignore it. The docstring quotes a residual of 37.00000004 degrees against an imposed 37,
and that figure reproduces exactly: one default load relaxed on the 45-degree hillside above finishes
at 37.00000004851246 degrees. Measured independently for this document, all four of the builds
tabulated below finish with a worst residual local slope of 37.00000003 degrees and a maximum slope
excess of 1.93e-9 to 2.00e-9 m, that is, about two nanometres. The residue is not a property of
sloping ground: the two flat-pad runs show it exactly as strongly as the two sidehill runs, which is
what the docstring's own explanation predicts, since what accumulates the rounding is the number of
transfers a cell is touched by rather than the shape of what lies underneath it. A micrometre is far
below any physical meaning on a pile and far above that residue.

## The verification sweep, and why it re-sweeps rather than repeating a fixed number of times

After the first cascade, `relax_to` runs a loop capped at 40 iterations:

```
prev = None
repeat at most 40 times:
    n_over = count_over_repose(..., floor=floor)
    if n_over == 0:                       stop, the field is relaxed
    if prev is not None and n_over >= prev:
        seed = cells_over_repose(..., floor=floor)      the offenders and their neighbourhoods
        if seed is empty:                 stop
        cascade seeded on `seed`
        recount; if the count did not fall, stop
        prev = new count; continue
    prev = n_over
    cascade over the WHOLE pad
finally, if verify: assert_stable(terrain, repose_deg)
```

The condition is progress, not a count of attempts, and the source is explicit about why. A fixed
three sweeps was a guess, and on sloping ground after a full dozer visit it was not enough: the
docstring records that the berm alone puts 208 pairs over the angle on a measured sidehill. Stopping
when the count stops falling is the honest condition, because it distinguishes "needs more sweeps"
from "cannot be relaxed", and only the second is worth raising over. The 40 is a backstop against a
pathological oscillation, not the expected exit.

The reseed branch exists because a stall is an artefact of the traversal order, not of the physics.
The cascade walks highest-first from wherever it is seeded, so a cell resolved early can sit below a
pair that only became over-steep afterwards, and nothing revisits the region. `cells_over_repose`
returns the offending cells, their partners and the full 8-neighbourhood of each, so the cascade has
somewhere to move material to; on a single 25 m spike on a flat pad that set is 9 cells. Seeding
directly on the offenders walks the region in a different order, which is what breaks the stall. The
docstring records three cases that motivated the loop, two in `relax_to` and one in the reseed branch
itself:

* a RIDGE CREST left 17 pairs with the worst at 44.0 degrees against an imposed 37, after a cascade
  over a floor cut transfers short and left cells that were never queued;
* a SIDEHILL after a full dozer visit, where the BERM alone put 208 pairs over the angle, which three
  fixed sweeps did not clear;
* and, on a sidehill, a reseed being the difference between four pairs left at 40.5 degrees and none.

### How often it actually fires

Instrumented by wrapping `relax.cascade`, `build.settle` and `build.relax_to` with counters and
running a real `build`, which is the only honest way to answer this. The harness is the one
`tests/test_build.py` uses, stated here so the numbers are reproducible: a 64 by 64 pad at 2.5 m
cells, `rectangular_yard(n_areas=1, area_width_m=90, area_length_m=90, bench_height_m=8)`, area access
at (90, 90), a four-truck `Fleet.of` at repose 37 with the shovel at (140, 140), and the PLAN
DEFAULTS for the lattice and the dozer cadence, in particular `loads_per_dozer_pass = 12`. The
sidehills are `topography.ground(FillType.SIDEHILL, 64, 64, 2.5, relief_m=...)`.

```
scenario                                 settle    relax_to   extra sweeps   residue at the STRICT angle
flat pad, 90 loads, 1 bench                  90           8              0   0 pairs, worst 37.00000003 deg
18 m sidehill, 90 loads, 1 bench             90           8              0   0 pairs, worst 37.00000003 deg
40 m sidehill, 200 loads, 2 benches         200          17              0   0 pairs, worst 37.00000003 deg
flat pad, 400 loads, 3 benches              400          34              0   0 pairs, worst 37.00000003 deg
```

Read the columns as: `settle` is the number of `settle` calls, each of which issues exactly two seeded
cascades (stage 3 never fired in any of these runs); `relax_to` is the number of `relax_to` calls,
each issuing one whole-pad cascade after a dozer pass; "extra sweeps" counts additional cascades
issued by the loop above. Every load was placed in all four runs, so the `settle` column is also the
load count, and the `relax_to` column is exactly `floor(loads / 12) + 1`, the periodic dozer visits
plus the one closing pass per area. That arithmetic is the check that the instrumentation is counting
what it claims to: 90 gives 7 + 1, 200 gives 16 + 1, 400 gives 33 + 1. On the 90-load 18 m sidehill
the total is 188 cascade calls, 90 plus 90 seeded and 8 whole-pad, with the loop adding nothing.

So on this harness the re-sweep loop is not the common path; it is not the path at all. It added zero
cascades in all four scenarios, and all four finished with ZERO pairs over the strict angle. Do not
read that as the loop being dead code: the cases that motivated it are recorded in the source, and
they are dozer and reclaim geometries on sloping ground rather than the plain build measured here.
What this table establishes is the cost of the common case, not the absence of the rare one.

The docstring records the shipped product's own matrix, which this document did not re-run because
those scenarios live in the consuming application rather than in this repository: nineteen of
twenty-one scenarios relax to zero pairs over the strict angle and use none of the assertion
tolerance; two sloping cases do not, a sidehill leaving four pairs at 40.5 degrees and a ridge crest
leaving two at 39.2, in both cases after the sweeps stopped making progress and a reseed on the
offenders failed to move them.

## `assert_stable` and `STABLE_TOL_DEG`

```python
assert_stable(terrain, repose_deg, *, tol_deg=STABLE_TOL_DEG) -> None    # raises ReposeViolation
```

It counts pairs at `repose_deg + tol_deg` with `floor=terrain.z0` and raises if any survive. The
message carries the count and the worst angle, because those are exactly the numbers needed to tell a
genuine solver failure from a caller that passed the wrong angle. Verified text, from a deliberately
unrelaxed 20 m spike on a flat pad:

```
ReposeViolation: 8 cell pairs stand more than 4.0 deg over the imposed repose angle of 37.0;
the worst local slope is 82.9 deg. Not relaxed.
```

`ReposeViolation` subclasses `AssertionError`. It is a named exception rather than a bare assert
because this is the failure mode that shipped to production once already and it should be greppable in
a log. Note the consequence of subclassing `AssertionError`: running Python with `-O` does not disable
it, since it is a real raise rather than an `assert` statement, but a caller catching
`AssertionError` broadly will swallow it.

```
STABLE_TOL_DEG = 4.0        degrees over the imposed angle before a pair counts as unrelaxed
```

**The tolerance is physical, not numerical**, and the source sets it from two requirements rather than
from what made a build pass. The angle of repose is not a constant: published handbook values for ores
span 34 to 60 degrees, and the figure moves with particle size, moisture and time since dumping.
Asserting a surface to a micrometre against a quantity known to a few degrees would be asserting the
wrong thing. So: it must catch the defect the invariant exists for, and the predecessor engine
finished with 446 pairs and a worst of 55.9 degrees against an imposed 37, an overshoot of 18.9
degrees, against which 4 degrees leaves a factor of nearly five in hand; and it must not flag residue
that is small against the uncertainty in the angle itself, and 4 degrees is a sixth of the published
spread for ores.

This is an anchored constant, in the sense that the 34-to-60 handbook span is a literature figure and
not a measurement of any specific material. What would replace it is a measured repose angle with a
measured uncertainty for the material being modelled, at which point the tolerance should be that
uncertainty. The source comment adds that the count and the worst angle are written into every
manifest at the STRICT angle, so residue is reported rather than hidden behind the tolerance; that
reporting happens in the consuming application, not in this package, and nothing in `bedblend` writes
a manifest.

## What consumes the returned move list

`cascade`, `relax_to` and `settle` all return `list[(source_cell, destination_cell, metres)]` in the
order the transfers happened, and the module docstring calls this ordering the point of the whole
function: "the highest unstable cell topples first, then whatever it destabilised, and so on down the
flank."

Check what reads it before relying on the stated purpose. Inside this package the return value has
exactly two consumers, and both are ledger updates, not physics:

* `build._carry` converts the thicknesses to volumes and calls `BlockModel.apply_transfers`;
* `reclaim.cut` does the same conversion inline after its own `relax_to`.

`BlockModel.apply_transfers` iterates the list in order and takes material off the TOP of each source
column, so the ORDER genuinely matters there: it determines which parcels move and how much
displacement each accumulates. That is a real dependence on the ordering and it justifies returning a
sequence rather than a set.

The docstring's further claim, that the ordered output "is the downslope coordinate the segregation
solver marches along, so this return value is what couples the geometry to the physics", is NOT what
the code currently does. Size segregation down a face is driven by `Placement.s_frac`, the down-face
position computed by `place_edge` at placement time, which `build` maps into bins of the
`FaceSegregation` result. Nothing in `facesegregation.py` or `segregation.py` reads a relaxation move
list. If that coupling is intended, it is unimplemented; as it stands, the sentence describes an
architecture rather than the running code.

## Calling it

`relax_to` for any operation that is not a fresh truck dump: a dozer pass, a reclaim cut, a synthetic
field. `settle` for a truck dump, so the fresh-heap stage runs.

```python
from bedblend.relax import relax_to, settle, assert_stable, count_over_repose

moves = settle(terrain, repose_deg=37.0, active=set(placement.cells))
moves = relax_to(terrain, repose_deg=37.0, active=set(cut.cells))
n_over, worst_deg = count_over_repose(
    terrain.z, terrain.nx, terrain.ny, terrain.cell_m, 37.0, floor=terrain.z0
)
```

Always pass `active` when you know which cells changed. It is the difference between a seeded heapify
and a whole-pad one on every single load. Do not pass it when you do not know: an incomplete seed set
is worse than none, and the module's third listed rewrite reason is exactly that a cascade seeded only
with the cells a deposit wrote can miss a neighbour that was already marginal.

`verify` defaults to True on `relax_to` and that is deliberate. The check is O(cells) against a solver
that is already O(moves log moves), so it is not the bottleneck, and the failure it catches is the one
that shipped. Turn it off only in an inner loop that verifies once at the end. `settle` always calls
`assert_stable` and offers no way to skip it.

## What this module is not

It is not a granular physics model. It does not predict the angle of repose; the angle is imposed by
the caller. It has no particles, no friction law, no cohesion, no pore pressure and no rate
dependence. Two piles of different material at the same repose angle relax identically here.

It does not produce avalanche statistics and no self-organized-criticality result should be read out
of it. The critical slope is fixed by the caller, which is precisely the condition under which SOC
does not apply.

It is not time-resolved. The two stages are two imposed angles applied in sequence, not an integration
over the hours a heap takes to slump. There is no timestep and no rate.

It does not lose material at the pad edge, ever, by design. If your pile reaches the boundary the
geometry is wrong and the solver will not tell you; check the boundary yourself.

It is not order-independent as a whole. Relaxing at 63.435 degrees and then at 37 gives a different
final surface from relaxing directly to 37, by up to 0.53 m on the six-load stack measured above. The
sequence of imposed angles is part of the model, not an implementation detail.

## References

* Bak, P., Tang, C. and Wiesenfeld, K. (1987). *Self-organized criticality: an explanation of the 1/f
  noise*. Physical Review Letters 59(4), 381-384.
  [doi:10.1103/PhysRevLett.59.381](https://doi.org/10.1103/PhysRevLett.59.381). The toppling rule, and
  the only citation the module carries.
* Young, A. and Rogers, W.P. (2021). Minerals 11, 636, figure 11. The 2:1 emplacement slope and the
  slump to repose, quoted verbatim in the module docstring as the justification for the two stages.
  The DOI [doi:10.3390/min11060636](https://doi.org/10.3390/min11060636) is carried in the repository
  README rather than in this module.
