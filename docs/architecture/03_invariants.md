# 03. Invariants: what the engine refuses to let drift

Five properties are held across the whole engine. For each one this document states the invariant, names
the function that enforces it, shows it holding and failing on real output, and says what goes wrong when
it is violated. Two of the five exist because they were violated in a shipped release, and the docstrings
that record those failures are quoted verbatim rather than paraphrased.

Every number below came from running the code in `bedblend/` at version `0.07.002`.

The tolerances, read out of `bedblend/relax.py` and `bedblend/blocks.py`:

```
    CONVERGE_TOL_M     1e-09   what the cascade solver settles each pair to
    VERIFY_TOL_M       1e-06   what the verifier allows, deliberately looser
    BARE_M             1e-03   below this a cell is carrying no material at all
    STABLE_TOL_DEG     4.0     degrees over the imposed angle before a pair counts as unrelaxed
    assert_consistent  1e-06   metres of disagreement between ledger and terrain
```

---

## Invariant 1: relaxation moves material and never creates or destroys it

### The statement

```
    sum over all cells of z[c], before a relaxation
      == sum over all cells of z[c], after it

    and for every returned transfer (a, b, t):
      z[a] decreased by exactly t   and   z[b] increased by exactly t

    z[c]   surface elevation at cell c, in metres
    t      transferred thickness, in metres
```

The pad boundary is a wall, not a sink. `neighbour_table` in `bedblend/relax.py` simply omits off-pad
neighbours, and its docstring names the consequence: "Material reaching the boundary stays on the pad
rather than falling off it, which keeps mass conservation exact; a pile that touches the boundary is
flagged by the caller instead of silently losing tonnes over the edge."

### What enforces it

Nothing asserts it. It is structural, and that is worth being explicit about. Inside `cascade` every
transfer is a paired statement and the record of it is emitted in the same breath:

```python
z[c] -= t
z[n] += t
moved = True
moves.append((c, n, t))
```

The deposition side has the same property by a different route. `_apply` in `bedblend/dump.py` normalises
a weight map to the requested volume before adding it, and its docstring states the guarantee: "Mass
conservation is exact by construction: the weights are normalised so the added volume equals the requested
volume, and no clipping happens afterwards. Any load whose footprint falls partly off the pad is
concentrated on the part that remains rather than losing tonnes over the edge."

`bedblend/dozer.py` uses paired statements throughout, including `build_ramp`, whose comment insists on
it: "EVERY MOVEMENT IS A RECORDED TRANSFER. The blade moves mass, and the lot ledger has to follow it cell
by cell; a scalar 'spoil' bucket would balance the terrain and silently desynchronise the provenance record
that the whole product rests on."

### Evidence

A 40 m spike dropped on the centre of a 41 by 41 pad at 2.0 m cells, relaxed to 37 degrees:

```
over-steep ordered pairs before: 8, worst 87.1376 deg
transfers returned: 351
sum(z) before 40.000000000000000
sum(z) after  39.999999999999993
absolute drift 7.105e-15 m of column height over 1681 cells
over-steep ordered pairs after: 0, worst 37.000000 deg
max slope excess after: 3.686e-09 m
```

`settle`, which runs a fresh-heap cascade at `FRESH_HEAP_DEG = 63.434949` degrees and then a settling
cascade at the repose angle, and a THIRD unseeded full-pad cascade when the census after the second
still reports pairs over the angle, on a 15 m column over a 31 by 31 pad:

```
settle returned 12 transfers; sum(z) drift 0.000e+00 m
```

End to end over a whole build, the strongest form. The reference 200-load run placed
`200 x 121.578947 m3` and the terrain reported `24315.7895 m3`; the 240-load two-bench run placed
`240 x 121.578947 m3` and reported `29178.9474 m3`. Both agree to the printed precision.
`tests/test_build.py::test_mass_is_conserved_through_the_whole_build` asserts the same thing with
`rel=1e-6`.

### What breaks if it is violated

Tonnage stops reconciling. `BlockModel.tonnes` multiplies thickness by cell area and bulk density, so lost
metres are lost tonnes, and the whole blending verdict is computed on a tonnage base: `vrr`,
`tonnage_weighted_variance` and the `1/N` bound in `bedblend/blending.py` all weight by mass. A drift of a
few tonnes changes the answer the product exists to give.

### The gap

There is no `assert_mass_conserved` anywhere in the package. A future operator that writes
`terrain.z[c] = value` instead of a paired transfer would not be caught by this invariant directly. It
would be caught indirectly by Invariant 2, which is the reason Invariant 2 is checked so often.

---

## Invariant 2: the ledger and the terrain agree, column by column

### The statement

```
    for every cell c:
        | sum of parcel thicknesses in column c  -  (z[c] - z0[c]) |  <=  tol_m

    z[c]    current surface elevation at c
    z0[c]   original ground at c, retained by Terrain from construction
    tol_m   1e-6 m by default
```

### What enforces it

`BlockModel.assert_consistent(terrain, tol_m=1e-6)` in `bedblend/blocks.py`. Its docstring:

> "Every column's parcels must add up to the material the terrain says is there. A disagreement means
> material was placed without being recorded or recorded without being placed, and every grade downstream
> is then wrong. Cheap to check and worth checking often."

`build()` calls it unconditionally once at the end of the run, and every `verify_every` sequence numbers
when the caller asks for it (off by default, `verify_every=50` in the build tests). The three functions
that keep it true are `BlockModel.record` on deposition, `BlockModel.apply_transfers` for dozer and
relaxation transfers, and `build._carry`, which is the single place a relaxation thickness becomes a
ledger volume.

### Evidence

A correct placement, then a deliberate desynchronisation on a 9 by 9 pad at 2.5 m:

```
recorded correctly, assert_consistent passes
after adding 0.30 m to the terrain and not the ledger:
   the ledger and the terrain disagree by 0.3 m at cell 40: ledger 1.25 m, terrain 1.55 m
```

The message carries the worst cell, both values and the magnitude, which is what is needed to tell a
missing `record` from a missing `apply_transfers`.

On the 240-load two-bench reference build the ledger holds 19782 parcels over 1740 occupied columns and
`assert_consistent` passes.

### It exists because it was violated

The failure is recorded in `bedblend/dozer.py`, in `level`:

> "ONLY PLACED MATERIAL CAN BE PUSHED. A dozer spreads the stockpile, it does not excavate the ground the
> stockpile sits on. Selecting high cells by elevation alone is correct on a flat pad and catastrophic on
> any of the four sloping fill types: on a sidehill the high ground IS the hill, and the blade drove a
> cell 4.43 m below the original surface, which is excavation nobody performed and which broke the ledger
> against the terrain."

The fix is the second clause of the `highs` filter, `terrain.thickness(c) > tolerance_m`, which stops the
blade from selecting a cell that is high because the ground under it is high.

A second, independent violation is recorded in `bedblend/reclaim.py`:

> "AND RECLAIM MUST RELAX. In the previous engine the cascade ran only on deposition and never after a
> cut, so a reclaimed face could stand at any angle indefinitely. Every function here returns the cells it
> touched so the caller relaxes and updates the ledger; `cut` does it directly."

### What breaks if it is violated

Every grade, every provenance fraction and every coarse fraction the product reports afterwards is
attached to the wrong place. The `reclaim.cut` comment states the mechanism: "relaxation MOVES MATERIAL,
and a ledger that is not told about the movement drifts away from the terrain, so every grade reported
afterwards is attached to the wrong place."

### The gap, and it is a large one

**`assert_consistent` checks thickness and nothing else.** It does not look at grade, `source_block`,
`grade_uncertainty`, `displacement_m` or `coarse_fraction`. Any defect that conserves thickness while
corrupting a parcel field passes it silently. That is not hypothetical: it is exactly what happened, and
`bedblend/blocks.py` keeps the record in `take_from_top`:

> "`replace`, NOT A POSITIONAL REBUILD, and the difference was forty percent of the coarse field. This
> rebuilt the departing slice by listing nine of `Parcel`'s TEN fields; `coarse_fraction` is the tenth and
> defaults to zero, so every slice that left was stamped with a coarse fraction of nothing. Thickness was
> conserved exactly, so the ledger-versus-terrain assertion passed. Grade, source block, event id, lift,
> area, uncertainty and displacement were all inside the nine, so provenance and grade both survived. The
> only field that died was the one no invariant covered, and it is the observable the entire segregation
> half of the product is measured on: the shipped reference pile read a thickness-weighted coarse fraction
> of 0.2093 against the 0.35 that was placed, with 43 cells at exactly zero, which is impossible for
> material that was put there."

The structural fix, and the reason it is a fix rather than a patch, is in the same comment: "`replace`
copies every declared field and overrides only what is named, so a field added to `Parcel` later is
carried without anyone having to remember it. That is the actual fix: not restoring one argument, but
making the class of bug impossible."

`Parcel` today has exactly ten fields, three of which carry defaults:

```
10 fields: z0_m, z1_m, grade, source_block, event_id, lift, area,
           grade_uncertainty, displacement_m, coarse_fraction
fields with defaults: grade_uncertainty, displacement_m, coarse_fraction
```

The three defaulted fields are precisely the ones a positional rebuild would silently zero. There are
three sites that split a parcel, and all three now use `dataclasses.replace`:
`BlockModel.take_from_top`, and both the FIFO and the FULL_HEIGHT branches of `reclaim._take`. The
`reclaim._take` comment cross-references the incident directly: "A rebuild that names the fields silently
drops any field added later, and that is not hypothetical: it is exactly how `coarse_fraction` came to be
zeroed on every split parcel in `blocks.py`, which put a 40 percent deficit into a shipped release with
every gate green."

On the 240-load reference build there are now zero parcels with `coarse_fraction` exactly zero.

---

## Invariant 3: no pair of cells stands steeper than the material can hold

### The statement

```
    for every ordered pair of 8-neighbour cells (c, n) with z[c] > z[n]:

        (z[c] - z[n]) - run * tan(repose_deg)  <=  VERIFY_TOL_M

        run = cell_m            for the four orthogonal neighbours
        run = cell_m * sqrt(2)  for the four diagonal neighbours

    with two exemptions, both because the angle of repose is a property of loose material:

      1. bare ground:       skip c entirely if  z[c] - z0[c] <= BARE_M
      2. inherited slope:   skip the pair if  (z0[c] - z[n]) - run * tan(repose_deg) >= -VERIFY_TOL_M
                            that is, if shedding every grain c holds would still leave it over the angle
```

Using one admissible drop for orthogonal and diagonal neighbours is the classic error here.
`critical_drop` says so: "Using one drop for both is the mistake that makes a relaxed cone come out
square."

### What enforces it

Three functions in `bedblend/relax.py`:

* `count_over_repose(z, nx, ny, cell_m, repose_deg, floor=...)` returns
  `(number of over-steep ordered pairs, worst local slope in degrees)`. This is the diagnostic, and its
  docstring says why it is a first-class function: "The diagnostic that caught the original defect, kept
  as a first-class function so the number can be reported rather than rediscovered."
* `assert_stable(terrain, repose_deg, tol_deg=STABLE_TOL_DEG)` raises `ReposeViolation` when
  `count_over_repose` at `repose_deg + tol_deg` returns anything non-zero.
* `relax_to(terrain, repose_deg, verify=True, respect_ground=True)` runs the cascade, sweeps until the
  count stops falling, reseeds on the offenders when it stalls, and then calls `assert_stable` by default.
  `settle` calls `assert_stable` unconditionally at the end.

`assert_stable` is reached from `relax_to`, from `settle` (called on every placed load), from
`_doze` through `relax_to`, and from `reclaim.cut` through `relax_to`.

### Evidence

A 20 m column on flat ground, before and after:

```
a 20 m column on flat ground: 8 over-steep pairs, worst 82.8750 deg
assert_stable raises ReposeViolation:
   8 cell pairs stand more than 4.0 deg over the imposed repose angle of 37.0;
   the worst local slope is 82.9 deg. Not relaxed.
after relax_to: 0 over-steep pairs, worst local slope 37.000000 deg
the strict check (tol 0) reports: (0, 37.00000002591147)
worst angle minus imposed: 0.000000026 deg
```

The residue of 2.6e-8 degrees is what `VERIFY_TOL_M` exists to absorb. The comment above it explains the
reasoning: "A cascade settles each pair to within `CONVERGE_TOL_M`, but a cell is touched by many
transfers and the rounding accumulates, so a converged field can sit a few nanometres over the line ...
Checking at the solver's own tolerance flags that as a failure, which would make the invariant cry wolf
and train a reader to ignore it."

The bedrock exemption, on a 5 by 5 pad at 2.5 m cut as a bare 60 degree hillside rising in x, with no
material placed on it at all. The pad size matters to the first number, since the pair count on a plane
is `(n - 1)(3n - 2)`: 52 here, 1220 on the 21 by 21 version of the same slope.

```
without floor: 52 pairs flagged, worst 60.0000 deg
with floor   :  0 pairs flagged, worst  0.0000 deg
```

That is the whole argument for `BARE_M` and the `floor` argument, and the docstring puts the measurement
next to it: "Measured on a sidehill and a ridge, this is what produced violations reported at 37.0 and
37.1 degrees against an imposed 37, which is the solver being correct and the check being wrong."

On the 240-load two-bench reference build the strict census reports zero pairs over 37 degrees and a
worst local slope of 37.0000 degrees.

### It exists because it was violated

From the `bedblend/relax.py` module docstring, first paragraph:

> "WHY THIS MODULE IS A REWRITE AND NOT A MOVE. The previous engine's relaxation left, on a measured run,
> 446 cell pairs standing steeper than the imposed repose angle, the worst at 55.9 degrees against an
> imposed 37. Those over-steep pairs are the spikes a reader sees in the rendered pile."

And from `ReposeViolation` itself:

> "A named exception rather than a bare assert because this is the failure mode that shipped to production
> once already, and it should be greppable in a log."

The specific mechanism is documented inside `cascade`, and it is the kind of bug that survives a test
suite:

> "THE CELL THAT GAVE MATERIAL AWAY GOT LOWER, AND THAT DESTABILISES THE CELLS ABOVE IT. This is the bug
> that produced the spikes. A highest-first queue processes an uphill neighbour BEFORE this cell, finds it
> stable, and never looks at it again; then this cell drops, the drop from that neighbour down to here
> grows past repose, and nothing re-queues it. The original solver pushed only the receivers and the
> toppling cell, so those pairs survived to the end of the run: 446 of them on a measured case, the worst
> at 55.9 degrees against an imposed 37."

### What breaks if it is violated

Two things, and only the first is visible. The obvious one is geometry: over-steep pairs are the spikes in
the rendered pile. The one that matters more is that `passable_mask`, `reachable_mask` and `step_ok` in
`bedblend/truck.py` are all computed from `terrain.z`, so an unrelaxed surface silently changes what is
drivable, which changes which tips are refused, which changes the pile. Invariant 5 depends on this one.

### The anchored constant

`STABLE_TOL_DEG = 4.0` is a judgement, and the source is explicit that it is set from two requirements
rather than from what made a build pass. It must catch the defect the invariant exists for (an overshoot
of 18.9 degrees, so four leaves a factor of nearly five in hand) and it must not flag residue small
against the uncertainty in the angle itself (published handbook values for ores span 34 to 60 degrees, so
four degrees is a sixth of the spread). What it costs is also recorded: "measured across the shipped
matrix: nineteen of twenty-one scenarios relax to ZERO pairs over the strict angle and use none of this
tolerance. Two sloping cases do not ... a sidehill leaving four pairs at 40.5 degrees and a ridge crest
leaving two at 39.2."

Nothing measured would replace it. A DEM study of the material would replace the repose angle itself, at
which point the tolerance would be set from that measurement's own spread.

### Where it can still fail

`relax_to` caps its sweep loop at 40 iterations and breaks out early when a reseed on the offenders does
not reduce the count. When that happens the surface is left as relaxed as the solver can make it and
`assert_stable` decides whether to raise. The count and the worst angle should be reported at the strict
angle, not at the tolerance, so a scenario that begins consuming the four degrees is visible.

---

## Invariant 4: the segregation split conserves species mass

### The statement

```
    the conservation law being integrated, from Gray and Thornton (2005) equation (3.18)
    reduced to one downslope dimension:

        d(phi)/dx + d(F)/dz = 0,        F(phi) = -Sr * phi * (1 - phi)

        phi   volume fraction of the SMALL (fine) species; index 0 is the layer BASE
        x     non-dimensional downslope coordinate, 0 at the crest to 1 at the toe
        z     non-dimensional depth through the flowing layer, nz = 32 cells
        Sr    the segregation number, equation (3.19):  Sr = q * L / (H * U)

    with the diffusive remixing of Gray and Chugunov (2006) carried on the same interfaces:

        Dr = Sr / Pe,       Pe = PECLET_DEFAULT = 12.0

    no-flux walls at the base and the free surface, which is what makes the scheme conservative:

        flux[0] = flux[nz] = 0

    sub-stepping honours whichever limit is tighter:

        hyperbolic:  CFL * dz / Sr           because |F'(phi)| = Sr * |1 - 2 phi| <= Sr
        parabolic:   CFL * dz^2 / (2 * Dr)

        CFL = 0.4,  dz = 1 / nz

    and the deposition identity that `split_base` guarantees, for a base fraction f:

        f * phi_deposited + (1 - f) * phi_remaining  ==  mean_phi   (before the call)
```

### What enforces it

`FlowingLayer.advance` and `FlowingLayer.split_base` in `bedblend/segregation.py`. The no-flux walls are
imposed by leaving `flux[0]` and `flux[nz]` at zero, which the docstring names as the reason the scheme is
conservative: "No-flux boundaries are imposed by setting the surface and base interface fluxes to zero,
which is the boundary condition in the source and is also what makes the scheme conservative." The
remixing term is carried on the same interfaces "so the scheme stays exactly conservative with it on: the
species-mass test passes unchanged rather than to a looser tolerance."

`split_base` states its identity as a test rather than a comment: "Species mass is conserved exactly by
construction, since `base_frac * phi_deposited + (1 - base_frac) * phi_remaining == mean_phi` before the
call. That identity is a test, not a comment."

### Evidence

Marching a layer at `Sr = 1.84`, which is close to the 1.8278 the 11 m reference dump below solves at,
through twelve steps of 1/12 in `x`, depositing 8 percent of the layer at each step:

```
nz 32  sr 1.84  pe 12.0  Dr 0.15333333333333335
split_base identity  f*phi_dep + (1-f)*phi_rest == mean_phi
  worst residual over 12 steps: 0.000e+00
advance() conserves the depth mean: 0.65000000000000002 -> 0.64999999999999991, drift 1.110e-16
```

The negative control, which the source calls C02, is exact rather than approximate:

```
Sr = 0: mean 0.65000000000000002, phi_dep 0.65000000000000002, phi_rest 0.65000000000000002,
        exactly equal: True
```

`split_base` short-circuits a uniform layer for exactly this reason: "the C02 negative control asserts
equality, not near-equality, because 'the solver did nothing' has to be provable rather than approximately
true."

End to end through `segregate_face` with the default material (`coarse_fraction = 0.35`), at three drops:

```
  drop  0.50 m  Sr 0.0406  flows True
     coarse mass total 0.350000000 (placed 0.350000000)  fine total 0.650000000 (placed 0.650000000)
     coarse on face 0.349888798  fine on face 0.649906751  overrun 0.000204451  TOTAL 1.000000000
  drop  1.38 m  Sr 0.2293  flows True
     coarse mass total 0.350000000 (placed 0.350000000)  fine total 0.650000000 (placed 0.650000000)
     coarse on face 0.348754434  fine on face 0.649777791  overrun 0.001467775  TOTAL 1.000000000
  drop 11.00 m  Sr 1.8278  flows True
     coarse mass total 0.350000000 (placed 0.350000000)  fine total 0.650000000 (placed 0.650000000)
     coarse on face 0.299158448  fine on face 0.649916120  overrun 0.050925432  TOTAL 1.000000000
```

Face-on-face plus overrun sums to 1.000000000 in every case, and each species sums to exactly the fraction
the load held. `Sr = 1.8278` at an 11 m face at 37 degrees also confirms the `PERCOLATION_COEFFICIENT`
anchor, which the module says is "set so that Sr for a reference dump ... comes out around 1.8".

A face that does not avalanche produces no sorting at all rather than a decorated stable slope:

```
a 30 deg face (below repose 37 less hysteresis 4): flows False, Sr 0.0000, overrun 0.0000
```

The sum-to-one guard on the split itself:

```
SizeSplit(coarse=0.4, fine=0.4) -> ValueError: a size split must sum to one, got coarse+fine = 0.8
SizeSplit.of(1.7)  clamps -> SizeSplit(coarse=1.0, fine=0.0)
SizeSplit.of(-0.2) clamps -> SizeSplit(coarse=0.0, fine=1.0)
```

### The boundary of this invariant, which is not documented anywhere else

**Species mass is conserved inside the solver and is not conserved across the coupling into the ledger.**
This is the most important thing in this document that no docstring currently states.

`build._run_one_load` does not redistribute species mass. It looks up a local coarse **fraction** per cell
and hands it to `model.record`:

```python
coarse = [seg.coarse_fraction_at(split, min(int(sv * nb), nb - 1)) for sv in pl.s_frac]
```

The thickness those fractions are weighted by is the dump operator's, produced by `_width_shape`,
`_mass_shape` and the lateral taper in `bedblend/dump.py`. `segregate_face` used its own twelve-bin mass
distribution, `w[k] = 0.35 + 0.65 * s_k` normalised, when it computed the fractions. Nothing requires the
two to agree, and they do not.

Measured on one OVAL edge dump. Configuration, stated in full because the numbers below depend on all of
it: a 40 by 40 pad at 2.5 m cells with every cell at `i < 20` raised to 10 m, giving a 10 m face at
`x = 50`; the load released at `(48.0, 50.0)` with the outward normal forced to `(1, 0)`;
`run_out_m = run_out_for_bench(10.0, 37.0) = 13.2704`; one truck load of 121.578947 m3; the default
material. The face segregation is `segregate_face(drop_m=10.0, face_angle_deg=37.0)`.

```
cells 24, asked 121.578947 m3, added 121.578947 m3
thickness-weighted coarse fraction of THIS placement: 0.290543288   (material 0.35)
the same profile weighted by segregate_face's own mass shape: 0.319720384
overrun_fraction 0.044656, overrun_coarse_fraction 0.997777
coarse fraction range across the placed cells: 0.0522 to 0.9770
segregation_index of the face profile: 0.358483
```

The gap decomposes cleanly into two mechanisms:

1. **The overrun accounts for 0.35 down to 0.31972, exactly.** Removing 0.044656 of mass at 99.7777
   percent coarse leaves `(0.35 - 0.044656 * 0.997777) / (1 - 0.044656) = 0.319720384`, which reproduces
   the measured value digit for digit. This is by design: what runs past the toe is nearly pure coarse
   and it is no longer on the face.
2. **The rest, 0.31972 down to 0.29054, is the two mass distributions disagreeing.** The dump operator
   puts 40.00 percent of the load's thickness in the crest half of the face against the 37.96 percent
   `segregate_face`'s own `w[k]` assumes, and the crest half is the fine-rich end.

There is a discretisation term inside the second mechanism worth naming, because it is the part that
moves with cell size rather than with the model. A 13.2704 m run-out over 2.5 m cells resolves to six
distinct down-face cell rows, so only bins 0, 2, 5, 7, 9 and 11 of the twelve receive any thickness at
all; the other six are weighted zero. Halving the cell size samples the profile more finely and moves
this number without anything in either model having changed.

There is a third, blunter consequence of the first mechanism. **The overrun mass is reported but never
moves.** Verified on the same dump: the operator was asked for 121.578947 m3 and put 121.578947 m3 on the
pad. `overrun_fraction` changes the composition attributed to the face; it removes no material from the
placement and deposits nothing beyond the toe. `segregate_face` is honest that trajectory segregation is
not modelled, but the reader should not infer that the mass it names has gone anywhere.

Over a whole build the effect is small, because most loads have small drops and therefore tiny `Sr`. On
the 240-load two-bench reference build:

```
thickness-weighted coarse fraction over the whole ledger: 0.348055491   (placed 0.35)
parcels with coarse_fraction exactly zero: 0
```

A 0.56 percent deficit, against the 40 percent deficit the `take_from_top` defect produced. It is small,
it is systematic, and nothing asserts a bound on it.

### What breaks if it is violated

The coarse fraction is the observable the segregation half of the product is measured on. `Cut.coarse_fraction`
in `bedblend/reclaim.py` is the plant-facing number, and its comment says why the field exists at all:
"Coarse runs to the toe of a dumped face; a campaign that cuts the toe therefore delivers coarse feed and
one that cuts the crest delivers fines, and until this field existed the engine modelled the sorting in
detail and then threw the answer away at the moment it became a plant-facing number."

### The gap

There is no assertion anywhere that the ledger's mass-weighted coarse fraction matches the material's
`coarse_fraction`, nor a stated bound on how far it may drift. The measurement above is the first record of
the magnitude. A gate of the form "the thickness-weighted coarse fraction over the whole ledger is within
one percent of `material.coarse_fraction`" would catch a recurrence of the `take_from_top` class of defect
directly rather than by inspection, and would have caught the original at 0.2093 against 0.35.

---

## Invariant 5: a tip that cannot be reached is recorded, not served

### The statement

Material never appears at a location no machine could have reached. When the plan asks for something the
pile no longer allows, the engine emits a record saying so and moves on. It never places the load anyway,
and it never silently drops the request.

`LoadRecord` states the intent:

> "A refused load is recorded with `placed=False` and its reason. Refusals are not failures to be hidden:
> they are the model reporting that the plan asked for something the pile no longer allows, and the count
> of them is a real measure of how good the dump plan was."

### What enforces it

Six sites, each returning a refusal value rather than raising or improvising.

| Site | Refusal value | Meaning |
|---|---|---|
| `build._nearest_reachable` | `None` | nothing drivable inside the area within `max_spot_offset_m` |
| `truck.solve_route` | raises `NoRoute` | no A* path over drivable ground |
| `build._run_one_load` | `LoadRecord(placed=False, refused_reason=...)` | either of the above, or an empty footprint |
| `build()` built-out branch | `LoadRecord(placed=False, ...)` | a routed load whose area has finished its programme |
| `reclaim.haul_cycle` | `HaulCycle(stand=None, ...)` | no reachable stand beside the cut, or no strict-goal route in to one |
| `reclaim.next_cut` | `None` | the pile in front of the face is worked out |

`NoRoute` is a named exception for the same reason `ReposeViolation` is: "A named exception because
refusing an unreachable tip is a RESULT, not an error to be swallowed. It is the model correctly reporting
that the pile has grown over its own access, and the caller is expected to pick another tip."

The refusal is not the first response. `_nearest_reachable` tries the plan, then searches outward over the
flood-fill result for the closest reachable cell **inside the same area**, and the deviation is recorded in
`LoadRecord.spot_offset_m`. The area constraint is what stops the deviation becoming a licence: "measured on
the reference scenario, 284 of 402 placed loads landed outside their own area, the road silted up, the
loading point was buried under material nobody planned to put there, and from that moment the flood fill
returned nothing reachable anywhere on the pad and every remaining load was refused."

### Evidence

The unit behaviour, on a 20 by 20 pad at 2.5 m:

```
_nearest_reachable with nothing reachable  -> None
_nearest_reachable with everything reachable -> the plan itself: True
```

An 8 by 8 plateau raised to 12 m, flood-filled from `(2, 2)` at `max_grade = 0.502369`:

```
reachable cells 340 of 400
is the plateau centre reachable? False
solve_route raises NoRoute: no drivable route to (26.0, 26.0): the pile has grown over its own
  access, or the tip sits on ground steeper than the equipment limit
```

The built-out branch, offering 900 loads against a programme that holds 417:

```
offered 900 placed 417 refused 483 rate 0.5367
    483  area 'ROM' is built out; its planned programme is complete
a refused record still carries its payload identity:
   seq 417 area 'ROM' bench -1 placed False grade 0.3080 source_block 20
```

A refused record keeps the payload's grade and source block, so the stream can be reconciled against what
was actually built.

The caller-error guard is the same idea applied one level up. A shovel inside a dump area would produce a
99 percent refusal rate with no visible cause, so `build()` refuses to start:

```
ValueError: the shovel at (60.0, 60.0) is inside dump area 'ROM'. The first load placed there will
bury the loading point and every later load will be refused for having no drivable start. Put the
shovel outside every area's footprint.
```

### What breaks if it is violated

The pile stops constraining its own construction, which is the first of the three couplings the engine is
built around. `bedblend/truck.py` states the mechanism: "This is the loop that makes a stockpile impossible
to feed repeatedly at one point: placing a load raises the ground, and raised ground stops being drivable."
Serve an unreachable tip and material accumulates wherever the plan happens to point, the refusal rate
stops being a measure of anything, and `BuildResult.refusal_rate` becomes decoration.

### Where refusal is degraded rather than recorded

Two places soften it, both deliberately, and both should be known.

`Fleet.depart` catches `NoRoute` and writes a single-point route instead of a refusal, because the load has
already been placed by then:

> "The load just placed can cut off the way out. That is a real and reportable situation: it is how a badly
> sequenced plan strands equipment. Record an empty departure rather than pretending the truck teleported
> home."

The consequence is that a stranded truck appears in the record as a `Route` with one point and
`placed=True`. Nothing counts those. A build with many of them would look clean.

`reclaim.haul_cycle` falls back to the reversed approach when the DEPARTURE will not solve:

> "The way out is the way in, reversed, which is the only honest fallback: the surface has not changed
> between the two solves, so if one direction routes and the other does not it is the asymmetry of the
> gradient rule and not a different pile."

That fallback covers the departure and only the departure. Two distinct conditions still produce
`stand=None`, and the caller cannot tell them apart from the return value: no cell beside the cut is
both passable and reachable (`best is None`), and a stand was found but `solve_route` in to it raised
`NoRoute` under `strict_goal=True`. The second is easy to misread as the first. The function's own
docstring describes only the first, saying `stand` is None "when nothing drivable is within reach of
the cut", so the docstring is narrower than the code; a caller distinguishing an undercut face from an
unroutable approach needs a field the type does not currently carry.

The `strict_goal=True` on both solves is deliberate and is the reason the approach can fail here where
a build-side dispatch would not: a truck parking to be loaded gets no exemption on its last step, while
a truck tipping over an edge does.

### A note on the reference scenario

The 200-load and 240-load configurations used throughout these documents produce **zero refusals**, and
setting `max_spot_offset_m=0.0` on the same scenario also produced zero, because every planned tip stays
reachable throughout. They therefore do not exercise this invariant end to end. The evidence above is at
the unit level plus the built-out branch. `tests/test_build.py::test_refusals_are_recorded_rather_than_hidden`
asserts a non-empty reason on every refusal, that the reason is one of access or the pad edge, that
strictly more than half of placed loads land exactly on plan, and that no spot offset exceeds
`max_spot_offset_m`. It bounds the refusal rate from above (`< 0.5`) and not from below, so it does not
require any refusal to occur.

---

## Summary

| # | Invariant | Enforced by | Failure mode when violated | Known gap |
|---|---|---|---|---|
| 1 | Relaxation conserves mass | structure: paired transfers, no off-pad neighbours | tonnage stops reconciling; every mass-weighted blending statistic moves | no assertion function; caught only indirectly by #2 |
| 2 | Ledger equals terrain, per column | `BlockModel.assert_consistent` | every grade and provenance number is attached to the wrong place | thickness only; a corrupted parcel field passes |
| 3 | Nothing stands over repose | `assert_stable`, `count_over_repose`, `ReposeViolation` | spikes in the geometry, and trafficability silently changes | `STABLE_TOL_DEG = 4.0` is a judgement; two sloping scenarios consume it |
| 4 | Species mass in the split | `FlowingLayer.advance`, `split_base` | the coarse fraction, the whole segregation observable, is wrong | holds inside the solver only; the ledger coupling drifts by 0.56 percent, unasserted |
| 5 | Refusal is recorded, not served | `_nearest_reachable`, `NoRoute`, `LoadRecord.placed` | the pile stops constraining its own construction | a stranded departure is degraded to an empty route and nothing counts it |

To check all five on a finished build:

```python
res.model.assert_consistent(res.terrain)                       # invariant 2
assert_stable(res.terrain, repose_deg)                         # invariant 3, with 4 deg of tolerance
count_over_repose(res.terrain.z, res.terrain.nx, res.terrain.ny,
                  res.terrain.cell_m, repose_deg,
                  floor=res.terrain.z0)                        # invariant 3, strict, report both numbers
assert res.terrain.volume_m3() == pytest.approx(               # invariant 1
    len(res.placed) * truck_spec.load_volume_m3, rel=1e-6)
```

Invariant 4's solver half is covered by the tests in `tests/test_segregation.py` and
`tests/test_material_segregation.py`. Its ledger half and invariant 5 have no single call that checks
them; both are described above with the measurement that would become one.

---

## References

Only sources the package's own docstrings cite.

* Gray, J.M.N.T. and Thornton, A.R. (2005). A theory for particle size segregation in shallow granular
  free-surface flows. *Proc. R. Soc. A* 461(2057), 1447-1473. doi:10.1098/rspa.2004.1420. Equations (3.10),
  (3.11), (3.18) and (3.19) are quoted with their numbers in `bedblend/segregation.py`.
* Gray, J.M.N.T. and Chugunov, V.A. (2006). *J. Fluid Mech.* 569, 365-398. doi:10.1017/S0022112006002977.
  The diffusive remixing term, and the source of the Peclet number of order ten.
* Bak, P., Tang, C. and Wiesenfeld, K. (1987). *Phys. Rev. Lett.* 59(4), 381-384.
  doi:10.1103/PhysRevLett.59.381. The toppling rule in `cascade`. `bedblend/relax.py` explicitly disclaims
  the self-organized-criticality results: "the critical slope is IMPOSED as the material's angle of repose
  rather than being a free parameter, and avalanche statistics are out of scope."
* Young, A. and Rogers, W.P. (2021). *Minerals* 11, 636. doi:10.3390/min11060636. The two-stage slope of a
  truck-dumped heap (figure 11), the dozer's role, and the statement that dozers displace material "in
  intractable ways", which is why `Parcel` carries `displacement_m` at all.
* Young, A. and Rogers, W.P. (2022). *Mining* 2(1). doi:10.3390/mining2010006. The measured dump geometry.
  The page range is given inconsistently inside this repository (86-102 in the module docstrings, 92-114 in
  `README.md`) and was not resolved against the publisher for this document.
