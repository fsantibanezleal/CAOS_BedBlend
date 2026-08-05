# 01. Overview: the module graph and the loop that makes it a system

This document describes how `bedblend` is put together and, more importantly, what turns seventeen
modules into one object. Every claim below was read out of the source or produced by running it. Where
a number appears, the run that produced it is named.

Everything here refers to the package at `bedblend/`, version `0.07.002` as declared in `pyproject.toml`
and `VERSION`.

---

## 1. The two halves of the answer

Sixteen of the seventeen modules do one thing correctly in isolation. `bedblend/build.py` runs the loop
that couples them, and its own module docstring is explicit that the loop is the product:

```
    for each area, for each bench:
        PADDOCK CAMPAIGN   heaps on the row lattice, building the base layer on the current floor
        DOZER              level it into a working floor, form the crest, raise the berm
        EDGE CAMPAIGN      radial sweeps, each load cascading over the face it is aimed at
    then RECLAIM           a sequenced face, cutting the lifts back out
```

That quoted schema is the specification, not a description of the call graph, and the difference
matters. The paddock campaign, the dozer and the edge campaign all run inside `build()`. **Reclaim does
not.** `bedblend/build.py` contains no import of `bedblend/reclaim.py`, verified by parsing the AST of
every module in the package:

```
does build import reclaim? False
does build import sectors/blending/rtd/stream/topography? []
```

What `build()` offers instead is the `after_load` hook, which is called with
`(len(result.placed), terrain, model)` after every placed load so a caller can run `reclaim.cut` or
`reclaim.next_cut` against the pile as it stands. The docstring says why: "BUILD AND RECLAIM ARE NOT
ALWAYS SEQUENTIAL. Some operations fill a pile and then take it down; plenty of others feed and draw at
the same time". A sequential campaign is the caller running `reclaim.campaign` on the returned
`BuildResult`, which is what `tests/test_build.py::test_reclaim_blends_the_input_stream` does.

---

## 2. The module graph

Derived by walking the AST of every `.py` file under `bedblend/` and collecting every relative
`from .x import ...`. This is the real graph, not a drawing of the intended one.

```
  tier 3    topography

  tier 2    build          reclaim         sectors         stream

  tier 1    blocks   relax   dump   dozer   truck   facesegregation

  tier 0    terrain   design   material   segregation   blending   rtd
            (no intra-package imports at all)
```

Edges, one line per module, complete:

```
    terrain          -> (none)
    design           -> (none)
    material         -> (none)
    segregation      -> (none)
    blending         -> (none)
    rtd              -> (none)

    blocks           -> terrain
    relax            -> terrain
    dump             -> terrain
    dozer            -> design, terrain
    truck            -> design, terrain
    facesegregation  -> material, segregation

    stream           -> truck
    sectors          -> blocks, design, terrain
    reclaim          -> blocks, relax, terrain, truck
    build            -> blocks, design, dozer, dump, facesegregation,
                        material, relax, terrain, truck

    topography       -> stream, terrain
```

Three observations a maintainer should carry.

`terrain` is the root of nearly everything, and it is not a data holder. It owns `crest_cells`,
`outward_normal`, `gradient` and `trafficable`, which are the fields that constrain every machine. Its
own docstring names that as the reason it exists: "Without a crest there is no face, so a truck dump
cannot cascade ... Without trafficability the pile does not constrain its own construction."

`segregation` is a tier-0 leaf. It imports nothing from the package, and for several releases nothing
imported it either. Its docstring keeps the record: "This module was complete and tested and nothing
called it; `facesegregation` stood in with three fitted curves while every document described these
equations." Today the only importer is `facesegregation`, and `build` reaches the solver only through
`facesegregation.segregate_face`.

The six modules outside `build`'s reach (`reclaim`, `sectors`, `blending`, `rtd`, `stream` and
`topography`) are the analysis and inversion half. `build` produces a `BuildResult`; the caller feeds
its `terrain` and `model` to those. Nothing in the build loop depends on how the result is measured.

---

## 3. The loop, as `build()` actually runs it

Signature, read with `inspect.signature`:

```python
build(
    terrain: Terrain, plan: DumpPlan, fleet: Fleet, payloads: list[Payload], *,
    repose_deg: float = 37.0,
    face_angle_deg: float | None = None,
    seed: int = 20260801,
    crest_drop_m: float = 1.0,
    max_spot_offset_m: float = 25.0,
    paddock_frac: float = 0.18,
    snapshot_every: int = 0,
    material: Material = DEFAULT_MATERIAL,
    route: Callable[[Payload], str] | None = None,
    verify_every: int = 0,
    after_load: Callable[[int, Terrain, BlockModel], None] | None = None,
) -> BuildResult
```

### 3.1 Preflight: the shovel guard

Before anything is built, `build()` checks `plan.area_at(*fleet.shovel_xy)` and raises `ValueError` if
the loading point sits inside a dump area. Run against a shovel at `(60, 60)` inside a 90 m area:

```
ValueError: the shovel at (60.0, 60.0) is inside dump area 'ROM'. The first load placed there will
bury the loading point and every later load will be refused for having no drivable start. Put the
shovel outside every area's footprint.
```

This is a caller error that would otherwise present as a 99 percent refusal rate with no explanation.

### 3.2 The queues

One queue per area, built once, before any load moves. For each bench in index order, `build()` computes
the bench's own run-out and then asks `plan.bench_program` for the ordered tip positions:

```
bench_height = max(bench.top_m - prev_top, 1e-6)
run_out      = run_out_for_bench(bench_height, face_deg)
```

The `prev_top` bookkeeping is load-bearing. The comment states the rule: "A bench's run-out depends on
ITS OWN height, not on how high its top sits above the pad. The second lift of a two-lift pile cascades
over its own face, not over both." `run_out_for_bench` is the horizontal component of the face:

```
    run_out_m = bench_height_m / tan(face_angle_deg)

    bench_height_m   height of THIS bench above the one below, in metres
    face_angle_deg   angle the tipped face stands at; clamped to [1, 89] degrees
                     defaults to repose_deg when face_angle_deg is None

    measured: run_out_for_bench(10.0, 37.0) = 13.2704 m
```

`plan.bench_program` splits the bench into a paddock lattice sized by `paddock_frac` of the designed
load count, then a sequence of edge-dump lifts on a footprint that shrinks by `lift_thickness_m /
tan(repose_deg)` per lift. The `paddock_frac` default in `build()` is `0.18`, and its own comment
explains the failure at a higher value: "Setting it too high starves the edge campaign: the load budget
is consumed in paddock dumps and no face is ever formed to cascade over, so none of the cascade physics
runs at all." Note that `DumpPlan.bench_program` and `DumpPlan.program` both default `paddock_frac` to
`0.35`; only `build()` passes `0.18`.

Each queue entry is `(TipPosition, run_out_m, bench_index)`.

### 3.3 Consuming the queues: two orders

Per payload, `build()` chooses the area:

```python
if route is not None:
    name = route(payload)                      # routed: several areas in progress at once
else:
    name = next((n for n in order if cursors[n] < len(queues[n])), order[-1])   # sequential
```

With a router the decision is made from the load's ore-control estimate, before placement, so a
misclassified load lands in the wrong pile and stays there. Without one, an area's whole programme is
finished before the next starts. A routed load sent to an area whose programme is complete is recorded
as refused rather than redirected, because "redirecting it would quietly break the one guarantee routing
exists to provide: that a class ends up where it was sent."

### 3.4 Per-load state, recomputed

Two fields are recomputed from the live terrain before every load:

```python
crest     = terrain.crest_cells(min_drop_m=crest_drop_m)
reachable = reachable_mask(terrain, fleet.shovel_xy, fleet.max_grade)
```

`reachable_mask` is one flood fill for the whole pad. The comment records why it is not a route solve
per candidate spot: "Asking it per candidate spot with a route solve each time took a build from 40 s
past 500 s."

`fleet.max_grade` is derived, not typed. `Fleet.of` computes it and states its provenance:

```
    max_grade = tan(repose_deg) / grade_limit_divisor

    grade_limit_divisor   default 1.5, the operational rule of thumb that trucks should not work
                          slopes approaching the angle of repose. NOT a measured constant.

    measured at repose_deg = 37: max_grade = 0.502369, which is 26.67 degrees,
    against a repose gradient of tan(37) = 0.753554
```

### 3.5 One load: `_run_one_load`

Dispatch, spot, place, settle, depart. In order:

1. `_nearest_reachable(terrain, tip, reachable, max_offset_m, area)`. The planned tip is tried first, so
   a feasible plan is followed exactly. Otherwise a bounded scan over the flood-fill result finds the
   closest reachable cell **inside the same area**. `None` means refusal.
2. `fleet.dispatch(...)` solves the approach with A* and calls `truck.spot`, returning
   `(discharge heading, distance to crest)`. `NoRoute` is caught and becomes a refusal.
3. The regime is chosen from the terrain, not from the plan's label:
   `at_face = tip.phase is Phase.EDGE and d_crest <= 3.0 * terrain.cell_m * 4.0`.
4. `classify(d_crest, truck.spec, rand=rng.next())` picks the profile, then `place_edge` or
   `place_paddock` writes the deposit into `terrain.z`.
5. `segregate_face` runs when `at_face and pl.s_frac`, producing a per-cell coarse fraction.
6. `model.record(...)` files the parcels.
7. `settle(terrain, repose_deg, active=set(pl.cells))` relaxes in two stages and `_carry` puts the
   resulting transfers into the ledger.
8. `fleet.depart(terrain, truck)` solves the way out **on the surface the load just changed**.

### 3.6 The dozer, on two cadences

Two separate triggers, both per area.

The reactive one runs when a load is refused for access:

```python
if not rec.placed and "no drivable ground" in rec.refused_reason and seq - last_doze[name] >= 2:
```

It runs an access-only visit and retries the same load once. The comment records the measurement that
forced it: "Measured: 1162 of 1320 planned tips refused for access and the pile stalled at 2.6 m, while
the SAME terrain came out fully reachable at the end, because the closing pass levelled everything after
the loads that needed it were gone." It also records what did not work: "Reopening only the RAMP was not
enough and the measurement said so plainly: identical placed count, identical profile census, identical
peak."

The periodic one runs on `plan.loads_per_dozer_pass` placed loads (default 12) and promotes itself to a
full visit every `plan.loads_per_full_pass` (default 60):

```
    access-only visit :  build_ramp, level, relax_to
    full visit        :  build_ramp, level, push_to_crest, build_berm, relax_to
```

The split exists because a berm is by construction a wall. From `_doze`: "Measured: with the full visit
on every access refusal the whole 1296-cell area came out unreachable at a peak of 3.2 m, and the peak
DROPPED across the visit, from 3.53 to 3.21, because the blade was taking the crown to build the wall
that was sealing the area."

Every area gets a closing pass at the end of the build, and it is access-only for the same reason.

### 3.7 Book-keeping through the loop

`snapshot_every` appends `(rec.seq, n_placed, list(terrain.z))` every N placed loads. `verify_every`
calls `model.assert_consistent(terrain)` every N sequence numbers and is off by default because it is
O(cells). `model.assert_consistent(terrain)` is called unconditionally once, at the end.

---

## 4. The three couplings, and where each one is in the code

The `build` docstring claims three couplings "that the previous engine did not have, and could not have
had". Each is a specific pair of lines.

### Coupling 1: the pile constrains itself

> "Every load is routed over the trafficable surface AS IT IS NOW. A tip the pile has grown over is
> REFUSED and recorded as refused, rather than being served anyway."

Where: `build()` recomputes `reachable_mask(terrain, fleet.shovel_xy, fleet.max_grade)` inside the
payload loop, so the mask is a function of the surface after the previous load. `_run_one_load` then
calls `_nearest_reachable`, which returns `None` when nothing inside the area is reachable within
`max_spot_offset_m`, and the record comes back with

```
no drivable ground inside area 'ROM' within 25 m of the planned tip: the pile has grown over its own
access here
```

The second gate is `fleet.dispatch` raising `NoRoute`, whose message is
`no drivable route to (x, y): the pile has grown over its own access, or the tip sits on ground steeper
than the equipment limit`. Verified directly: on a 20 by 20 pad at 2.5 m with an 8 by 8 plateau raised to
12 m, `reachable_mask` from `(2, 2)` marks 340 of 400 cells reachable, the plateau centre is not among
them, and `solve_route` to a plateau cell raises `NoRoute`.

The constraint that makes this bind rather than leak is inside `_nearest_reachable`: the alternative spot
must satisfy `area.contains(x, y)`. Its docstring records the measurement from when it did not: "measured
on the reference scenario, 284 of 402 placed loads landed outside their own area, the road silted up, the
loading point was buried ... and from that moment the flood fill returned nothing reachable anywhere on
the pad and every remaining load was refused."

### Coupling 2: the face decides the shape

> "The dump profile is chosen from the truck's measured distance to the live crest, and oriented along
> the crest normal, so the deposit geometry is an output of the build state rather than a setting."

Where, in `_run_one_load`:

```python
heading, d_crest = fleet.dispatch(terrain, truck, actual, payload, crest=crest)
...
at_face = tip.phase is Phase.EDGE and d_crest <= 3.0 * terrain.cell_m * 4.0
if at_face:
    profile = classify(d_crest, truck.spec, rand=rng.next())
    pl = place_edge(
        terrain, dx, dy, truck.spec.load_volume_m3, truck.spec,
        profile=profile, run_out_m=run_out_m,
        normal=(math.cos(heading), math.sin(heading)), distance_to_crest_m=d_crest,
    )
```

`d_crest` comes from `truck.spot`, which walks the live crest list and, when the nearest crest cell is
within `3.0 * tip_reach(terrain)`, replaces the truck's reversing heading with
`terrain.outward_normal(best_c)`. The two thresholds agree by construction and by arithmetic:
`tip_reach` is `4.0 * terrain.cell_m`, so `spot` switches to the crest normal at `12 * cell_m`, and
`at_face` is true at `3.0 * cell_m * 4.0`, the same `12 * cell_m`. At a 2.5 m cell both are 30.0 m,
confirmed by evaluating both expressions.

Inside that window the profile is then decided by distance alone, with one exception:

```
    distance_to_crest_m > 1.0 * truck.body_length_m  ->  SLOUGHED_HEAP
    otherwise                                        ->  OVAL / COMET / RECTANGULAR, drawn from
                                                         their measured frequencies

    body_length_m default 12.9 m (CAT 793F class)
```

So on a 2.5 m pad there is a band from 12.9 m to 30.0 m in which a load is treated as an edge dump and
is guaranteed to form a sloughed heap. That band is real and it is thin: on the 200-load reference run
below, 124 of 125 at-face loads were inside 12.9 m and exactly one fell in the band.

### Coupling 3: the ledger follows the material

> "Every operation that moves material, deposition, relaxation, dozing and reclaim alike, carries the
> block ledger with it, and the invariant is checked."

Where, exhaustively:

| Operation | Ledger call | Site |
|---|---|---|
| deposition | `model.record(...)` | `_run_one_load` |
| settling after a dump | `_carry(model, terrain, moves)` | `_run_one_load`, after `settle` |
| ramp cut and fill | `model.apply_transfers(r.transfers, ...)` | `_doze` |
| levelling | `model.apply_transfers(p.transfers, ...)` | `_doze` |
| crest push | `model.apply_transfers(q.transfers, ...)` | `_doze`, full visit only |
| berm | `model.apply_transfers(b.transfers, ...)` | `_doze`, full visit only |
| relaxation after a dozer visit | `_carry(model, terrain, relax_to(...))` | `_doze`, both branches |
| reclaim | `model.apply_transfers(...)` | `reclaim.cut`, not `build` |
| the check | `model.assert_consistent(terrain)` | `build`, at `verify_every` and at the end |

`_carry` exists so that exactly one place converts a relaxation thickness into a ledger volume:

```
    volume_m3 = thickness_m * model.cell_area_m2

    cell_area_m2 = cell_m ** 2 ;  at cell_m = 2.5, a 1.0 m transfer is 6.25 m3
```

Its docstring is blunt about why: "Getting that conversion wrong is silent and catastrophic, which is
why it lives in exactly one place."

---

## 5. What a reference run actually produces

Configuration: a 64 by 64 pad at 2.5 m cells, one 90 m by 90 m area with one 8 m bench, `row_spacing_m`
10, `tip_spacing_m` 8, `loads_per_dozer_pass` 40, access at `(90, 90)`, a four-truck CAT 793F fleet with
the shovel at `(140, 140)`, 200 payloads, `repose_deg` 37, `seed` 20260801.

```
loads offered       200
placed              200
refused             0
dozer visits        6          (_doze calls; 16 DozerPass records)
profile census      {'paddock': 75, 'oval': 77, 'comet': 25, 'rectangular': 22, 'sloughed_heap': 1}
rng draws consumed  125
placed by phase     paddock 75, edge 125
peak surface        4.5965 m
volume              24315.7895 m3   (200 x 121.578947 m3, exact)

model.mean_displacement_m()   21.6453 m
mean LoadRecord.spot_offset_m  0.0000 m   (every load landed on its planned tip)
```

Those last two are different quantities and the run separates them cleanly. `mean_displacement_m` is
the tonnage-weighted distance the DOZER and the relaxation have since shoved the material; the spot
offset is how far the truck stood from the tip the plan asked for, and here it is zero for all 200.

The draw count is the diagnostic worth remembering: 125 draws for 125 at-face loads and not one more.
Nothing else in the build consumes randomness.

Segregation reaching the ledger, same run:

```
loads with a non-zero segregation_index   98
segregation_index                          0.000017 to 0.236143
sr                                         0.000043 to 0.718664
drop_m                                     0.0162 to 4.3250, median 0.8186
ledger coarse fraction per column          0.2056 to 0.8443 over 1708 occupied columns
```

The same configuration with two benches and 240 loads gives 240 placed, zero refused, a peak of 7.1475 m
and 19782 parcels over 1740 occupied columns. `model.assert_consistent` passes and the strict repose
census reports zero pairs over 37 degrees.

Two honest notes on that run. It has **no refusals at all**, so it does not exercise the refusal path;
setting `max_spot_offset_m=0.0` on the same scenario also produced zero refusals, because every planned
tip stays reachable. Forcing the refusal branch on this scenario requires offering more loads than the
programme holds, which produces the built-out refusal instead (483 of 900 at that count). The
access-refusal path is exercised at the unit level in section 4 and in `tests/test_build.py`.

---

## 6. What the loop is not

It is not a discrete-event simulator. `Fleet` says so: "Deliberately NOT a discrete-event simulator.
Queue times, bunching and dispatch optimisation are a different product." Trucks are selected round
robin by `fleet.trucks[seq % len(fleet.trucks)]` and there is no clock anywhere in `build.py`.

It does not generate its own stream. `payloads` is the caller's, in arrival order, and the docstring
explains the refusal: "This function does not generate it, because how the pit is dug is a property of
the operation, not of the pile." `bedblend/stream.py` provides `dig_sequence` and `payloads_from` for
callers who want one.

It does not run reclaim, as established in section 1.

It does not model trajectory segregation. `segregate_face` reports an `overrun_fraction`, and that mass
is **not** removed from the placement. Verified on a single edge dump: the operator was asked for
121.578947 m3, `overrun_fraction` came back as 0.044656, and the volume added to the pad was
121.578947 m3. The overrun changes the composition reported on the face; it moves no material.

---

## 7. Anchored constants visible from the loop

Each of these is a stated parameter rather than a measured constant. Replacing any of them is a
parameter change, not a code change.

| Constant | Value | Where | What would replace it |
|---|---|---|---|
| `grade_limit_divisor` | 1.5 | `Fleet.of` | A site's own equipment gradient limit. |
| `paddock_frac` | 0.18 in `build`, 0.35 in `DumpPlan` | `build`, `bench_program` | The source describes the base layer without quantifying it. |
| `crest_drop_m` | 1.0 m | `build` | The drop that makes a cell a crest cell on a given pad resolution. |
| `max_spot_offset_m` | 25.0 m | `build` | How far an operator will actually deviate from a planned tip. |
| `SLOUGH_DISTANCE_TRUCK_LENGTHS` | 1.0 | `dump` | A rule of thumb, not a measured constant. |
| `at_face` window | `12 * cell_m` | `build`, `truck.tip_reach` | Expressed in cells so it scales with pad resolution. |
| `DEFAULT_PUSH_M` | 40.0 m | `dozer` | Typical efficient push distance for a large track dozer. |
| `DEFAULT_BLADE_M3` | 30.0 m3 | `dozer` | Blade capacity per pass. |
| `PERCOLATION_COEFFICIENT` | 0.30 | `facesegregation` | A DEM run or the laboratory characterisation test. Not run for this release. |
| `PECLET_DEFAULT` | 12.0 | `segregation` | Gray and Chugunov fit it against chute experiments and report order ten. |

---

## 8. Version reporting, and a caveat

`bedblend.__version__` is read from packaging metadata, not from a literal:

```python
try:
    __version__ = _pkg_version("bedblend")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
```

The comment records why: a hand-maintained literal "had drifted two releases behind `pyproject.toml`:
the module reported 0.05.002 while 0.06.001 was on PyPI".

The mechanism has its own failure mode and it is live in the development environment used to write this
document. `importlib.metadata` reports the **installed distribution's** version, not the source tree's.
With the package imported from the working tree and a stale editable install alongside it,
`bedblend.__version__` returned `0.5.0` while `pyproject.toml` and `VERSION` both said `0.07.002`.
Anything that logs the engine version next to a result should be reinstalled before it is trusted.

---

## 9. References

Only sources cited by the package's own docstrings are listed. Where a docstring gives no DOI, the DOI
comes from `README.md` in this repository.

* Gray, J.M.N.T. and Thornton, A.R. (2005). A theory for particle size segregation in shallow granular
  free-surface flows. *Proc. R. Soc. A* 461(2057), 1447-1473. doi:10.1098/rspa.2004.1420. Cited by
  `bedblend/segregation.py` with equation numbers (3.10), (3.11), (3.18), (3.19).
* Gray, J.M.N.T. and Chugunov, V.A. (2006). *J. Fluid Mech.* 569, 365-398.
  doi:10.1017/S0022112006002977. Cited by `bedblend/segregation.py` for the diffusive remixing term.
* Bak, P., Tang, C. and Wiesenfeld, K. (1987). *Phys. Rev. Lett.* 59(4), 381-384.
  doi:10.1103/PhysRevLett.59.381. Cited by `bedblend/relax.py` for the toppling rule only; the
  self-organized-criticality claims are explicitly disclaimed there.
* Young, A. and Rogers, W.P. (2021). *Minerals* 11, 636. doi:10.3390/min11060636. Cited throughout for
  the two dumping phases, the volume of influence, the crest and the dozer's role.
* Young, A. and Rogers, W.P. (2022). *Mining* 2(1). doi:10.3390/mining2010006. Cited by
  `bedblend/dump.py` and `bedblend/terrain.py` for the 28 UAV-surveyed dumps and the four profiles.
  **Page range is inconsistent inside this repository**: the module docstrings give 86-102 and
  `README.md` gives 92-114. Neither was verified against the publisher for this document.
* Cogent Engineering 4(1), 1387955. doi:10.1080/23311916.2017.1387955. Cited by `bedblend/terrain.py`
  and `bedblend/design.py` for waste-dump lift and ramp construction.
* Neufeld, C., Lyall, G. and Deutsch, C.V. (2006). CCG Report 8, paper 306. No DOI given in the source.
  Cited by `bedblend/stream.py`, `bedblend/blocks.py`, `bedblend/design.py`, `bedblend/dozer.py`,
  `bedblend/build.py` and `bedblend/sectors.py`, which is every module that names it.
* Baffinland, Life-of-Mine Waste Rock Management Plan (2017). No DOI given in the source. Cited by
  `bedblend/dozer.py` for dozer operators determining truck access.

---

## 10. Where to go next

* `docs/architecture/02_determinism.md` for the generator, the one stochastic choice, and the
  reproducibility contract.
* `docs/architecture/03_invariants.md` for the five things the engine refuses to let drift, and what
  breaks when each is violated.
