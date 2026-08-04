# Changelog

All notable changes to `bedblend` are recorded here. The format follows Keep a Changelog, newest on
top, and the versions follow `X.XX.XXX` (the manifest carries the semver form with the padding
dropped).

## [0.05.001] - 2026-08-03

### Fixed

- `relax_to` sweeps until the count of over-steep pairs stops falling, rather than a fixed three
  times, and reseeds a stalled cascade on the offenders and their neighbourhood. The cascade walks
  highest-first from wherever it is seeded, so a stall is an artefact of that order. On a
  cross-valley fill this took the residue from 17 pairs at 45.9 degrees to none.

### Changed

- `assert_stable` takes a tolerance, `STABLE_TOL_DEG`, defaulting to 4 degrees, and `cells_over_repose`
  is exported for the reseed. The tolerance is set from two requirements rather than from what made a
  build pass: it must catch the defect the invariant exists for, which was 446 pairs with the worst at
  55.9 degrees against an imposed 37, and it must not flag residue small against the uncertainty in
  the angle itself, which for ores spans 34 to 60 degrees. Nineteen of twenty-one measured scenarios
  relax to ZERO pairs over the strict angle and use none of it.
- A cell carrying less than a millimetre of material is treated as bare. It cannot stand at an angle:
  shedding everything it has leaves the ground.

## [0.05.000] - 2026-08-03

### Fixed, and every one of these was measured rather than reasoned about

- **Trafficability was the wrong test.** A cell was undrivable if ANY of its eight neighbours was
  steep, which on a pile at repose condemns the whole crest, the whole perimeter and the toe of every
  face. The working level was unreachable by construction. It is now the local surface tilt by
  central differences, and whether the next cell can be reached is asked separately, per step, by
  both the flood fill and the router. A graded ramp cut into a clean 8 m platform went from 30 of
  1296 cells reachable to 1286.
- **The access point defaulted to a corner inside the pile.** It is the midpoint of the open edge.
- **The ramp was a reserved void.** A corridor that must rise to the working level needs as much fill
  as a share of the bench, shoved in sideways by a blade with a fifteen-metre reach, while the trucks
  that could supply it are forbidden from driving there. Trucks now fill the whole area and the dozer
  CUTS the road back into it. `build_ramp` also only ever filled, so a buried corridor returned zero
  transfers and did nothing.
- **The ramp was graded to exactly the machine limit,** so drivability was decided by rounding. It is
  built at 85 percent of the limit, and the corridor spans the area rather than stopping at its
  centre, which takes the lift it can serve from about 19 m to 34 m.
- **A refused tip could be re-spotted outside its own area,** which is a licence to tip in the haul
  road. It silted up the access and buried the loading point, after which nothing on the pad was
  reachable. Alternative spots are confined to the area.
- **Dump areas sat flush against the pad origin,** so a dump on the near edge cascaded off the array:
  221 of 766 planned tips on the reference scenario lost to the edge of an array. Areas are offset by
  a margin.
- **The stability invariant flagged steepness it was impossible to clear.** A cell carrying a thin
  skin over ground that already stands steep can shed every grain it has and still be over the angle.
  The cascade knew this and declined to move anything; the check did not, so a build died on a
  surface that was as relaxed as it can physically be. Measured on a sidehill: 65 pairs, worst 49.1
  degrees, every one inherited from the landform.

### Changed

- `bench_program` fills a bench in LIFTS on a shrinking footprint, each inset by the horizontal run
  of a face at repose, and each carrying only the volume its own footprint holds at one lift
  thickness. It used to emit one lattice and one set of sweeps per bench and declare it complete:
  332 tips against a design of 1360.
- A bench's designed volume is the actual frustum at repose, by the prismatoid rule, not a blunt
  fraction of its bounding box. The fraction asked a 60 m square to hold 51,500 cubic metres of a
  shape whose capacity is 27,100.
- The dozer cadence is split: access work (grade the ramp, level the floor) every 12 loads, and the
  full visit that adds the crest push and the safety berm every 60. A berm is by construction a wall,
  and running it on the access cadence ringed the area.
- `level` accepts a `band_m` that restricts the blade to the working bench. It is NOT used by the
  default build: it was tried and the measurement did not support it, taking the peak from 13.6 m to
  12.0 and breaking three reclaim invariants.

### Result on the reference scenario

744 of 766 planned loads placed, zero refused for access, the designed volume delivered to within
three percent, and the surface passing every invariant. Before this release the same scenario placed
298 loads with 47 percent refused, and 284 of those 298 had landed outside their own dump area.

## [0.04.001] - 2026-08-03

### Fixed

- `settle` sweeps the whole pad when its seeded second pass leaves anything standing over the angle
  of repose. With a ground floor a cell's transfer can be cut short by the rock beneath it, and the
  cell it would have fed is then left marginally over the angle without ever having been queued.
  Measured on a valley fill: four pairs at 38.2 degrees against an imposed 37. The check is O(cells)
  and the extra sweep only runs when it is needed, so correctness costs nothing on the common path.

## [0.04.000] - 2026-08-03

### Changed

- BREAKING: a snapshot is now `(seq, placed, surface)` rather than `(placed, surface)`. The sequence
  number of the load just placed is what lets a player show the truck that is WORKING RIGHT NOW
  instead of every path ever driven, which is the difference between watching a build and looking at
  a diagram of one.

## [0.03.002] - 2026-08-03

### Added

- `build(snapshot_every=N)` records the surface every N placed loads into `BuildResult.snapshots`,
  so a consumer can animate the build instead of only inspecting the finished pile. A build that
  ships one final state can show what was made but never how, and the how is the product: the base
  layer going down, the dozer levelling it, the crest advancing.

## [0.03.001] - 2026-08-03

### Fixed

- `build` takes `paddock_frac`, the share of a bench laid as base layer before the edge campaign
  starts. It was fixed at 0.35 inside the plan, which starved the edge campaign on a tall bench: the
  whole load budget went into paddock dumps, no face was ever formed, and none of the cascade physics
  ran. A base layer is one lift of heaps, roughly a sixth of an 18 m bench, so the default is 0.18.

## [0.03.000] - 2026-08-02

The physics the engine was missing. 0.02.000 rebuilt the geometry correctly but still carried three
quantities as single constants that are not constants, and it shipped a segregation solver that
nothing ever called.

### Added

- `material`. Density is not one number: rock is dense in the ground, SWELLS when blasted and loaded,
  and COMPACTS again under traffic. Hard-rock swell is 30 to 45 percent and achievable compaction 5 to
  15 percent, approached over 20 to 30 equipment passes rather than linearly. The angle of repose is
  not a constant of the ore either: it rises with a little moisture through capillary cohesion and
  collapses past saturation, so it is now a function rather than a setting. And a load carries a size
  split, because a model with one size per load cannot segregate at all.
- `facesegregation`. The coupling that was missing. Gray and Thornton's solver was in the package and
  was never applied, because in the old product nothing ever formed a face for an avalanche to run
  down. Coarse now runs to the toe and fines stay near the crest, more strongly from a taller and
  steeper face, with part of the coarse rolling BEYOND the toe. Three published drivers, all of them
  quantities the engine already had: drop height, face angle, and the material's own size spread. A
  single-sized material or a flat tip produces no sorting at all, which is the degenerate case that
  proves the model is not just painting a gradient on everything.
- Routing. `build` takes a `route` hook mapping a load to the area its declared class belongs in, so
  several areas are under construction at once and a class ends up where it was sent. Sectors only
  exist because of routing; a yard without it has one sector and nothing to compare.

### Fixed

- **The berm walled the working area off from itself.** A continuous berm along every crest cell is
  not a berm, it is a wall, and it made refusals go UP the more the dozer ran: 62 percent at a pass
  per 10 loads against 33 percent at a pass per 40. Real tip heads have breaks in them. With gaps,
  refusals fall to 19.2 percent at the default cadence and 30.8 percent at the tight one.

### Changed

- The block ledger records a coarse fraction per parcel, so a cell near the toe of a face reads
  coarser than one near its crest. Measured across a 240-load build, the coarse fraction spans 0.000
  to 0.395 against a uniform input of 0.350.

## [0.02.000] - 2026-08-02

The engine is rebuilt around what a truck-built stockpile actually is. Version 0.01.000 modelled a
pile that received material at arbitrary coordinates from an event record, relaxed toward an isotropic
cone, and was built with geometries that belong to conveyor stackers. It had no trucks, no dump plan,
no lifts and no access constraint.

### Fixed

- **The dozer excavating the hillside.** `level` selected material to push by ELEVATION alone, which
  is right on a flat pad and wrong on any sloping site: on a sidehill the high ground is the hill, so
  the blade drove a cell 4.43 m below the ground it started from. Only placed material can be pushed
  now, capped by what is actually there.
- **Relaxation eroding original ground.** The cascade treated elevation as free-floating and would
  avalanche bedrock. It now takes the original ground as a floor, so a cell can shed at most the
  material sitting above it, and the stability check skips cells carrying nothing, because the angle
  of repose is a property of loose material and a natural hillside is entitled to stand steeper.

- **The spikes.** When a cell topples it gets lower, which destabilises the cells ABOVE it. The
  relaxation re-queued only the cells that received material, so with a highest-first queue an uphill
  neighbour was checked once, found stable, and never revisited after this cell dropped below it. A
  converged-looking relaxation left 446 cell pairs standing at up to 55.9 degrees against an imposed
  37. Now zero, and the invariant is asserted rather than assumed.
- **A hang the first fix exposed.** When every candidate transfer falls at or below tolerance nothing
  moves, but the cell was re-queued anyway and the loop only bounds the number of moves. Re-queueing
  now requires real progress, which also makes termination provable.
- **The ledger detaching from the ground.** `cut` relaxed the terrain without telling the block
  ledger, drifting 0.458 m on a single cut, after which every reported grade was attached to the
  wrong place. Anything that relaxes now carries the ledger, inside the operator rather than left to
  the caller.
- **Provenance reported to 1e-12.** With a dozer in the model that precision belongs to the
  simulation, not to any operation. Measured mean displacement on a test build is 7.34 m, and
  provenance now carries it.

### Added

- `terrain`, the ground plus the two derived fields that constrain every machine: the crest of the
  working level, and trafficability.
- `design`, the dump plan: named areas with a bench schedule and a reserved access ramp. A real dump
  record locates a load by the "name and bench height of dump location polygon", so areas and levels
  are the operational data model rather than an abstraction.
- `dump`, two placement regimes. A paddock heap is an elliptical frustum sized by the truck itself; an
  edge dump cascades down the face perpendicular to the crest tangent. Calibrated against 28
  UAV-measured dumps (doi:10.3390/mining2010006, table 5): length 13-46 m, width 11-23 m, thickness
  0.37-2.03 m. All four measured profiles are produced, selected by distance to the crest.
- `dozer`, which levels the floor, pushes material over the face, raises berms, and reports how far it
  displaced everything.
- `truck`, machines with A* routes over drivable ground, spotting, and retained approach and departure
  paths.
- `blocks`, the raw ledger at truckload support, carrying grade uncertainty and displacement.
- `sectors`, working-region rollups and the raw-versus-model comparison, reproducing the published
  behaviour that the model interval is tighter than the data interval in every region.
- `reclaim`, sequenced extraction from a face in LIFO, FIFO or full-height order.
- `build`, the loop that makes the above a system.

### Changed

- `stream` is rewritten. It used to take `range_t`, the practical range of the grade covariance, as an
  input. That is backwards: consecutive trucks load from the same dig block, so the correlation length
  is set by the shovel's dwell. It now takes the dig sequence and REPORTS the range that resulted.
  Measured on 800 loads: dwell 5, 20 and 60 gives 1098, 7789 and 13865 tonnes.

### Removed

- `stacking`, which offered chevron, windrow, cone shell, chevcon and strata as build geometries for a
  pile fed by trucks. Those are conveyor-stacker geometries; of the five pre-crusher stockpile types
  only blended-in-blended-out is a chevron. Trucks do not build a chevron bed.
- `heightfield`, `pile`, `run` and `schema`, replaced by the modules above.

- `topography`, ground that is not flat. Only one of the five published stockpile fill types is a
  prepared flat pad; the others are sidehill, valley, cross-valley and ridge-crest fill, and the
  ground decides where equipment can go before a single load is placed. Measured on a 30 m landform
  at the equipment limit, buildable ground is 100 percent on a flat pad and 72 percent in a valley or
  along a ridge.

### Known limits

- About a third of planned tips are refused on a two-bench build because the pile grows over its own
  access. The physics is right and the refusals are reported with reasons, but the berm is raised with
  no gap in it. Tracked as F-011.

## [0.01.000] - 2026-08-01

First release. The engine was extracted from the StockTwin product repository, where it had been
written as an internal package. An internal package advertises a library nobody can install, so the
engine now lives in its own repository and StockTwin consumes it as a pinned dependency, which is the
same shape as `milldem` for ChargeCascade and `minehaulsim` for DispatchLab.

### Added

- `heightfield`: mass-conserving relaxation to an imposed angle of repose. A priority cascade with a
  water-filling toppling rule, so a cell sheds to several downslope neighbours at once and the
  ordered transfers are the avalanche path the segregation solver then marches along.
- `segregation`: the Gray-Thornton kinetic sieving equation in the flowing layer, solved with a
  Godunov flux on a convex flux function so the concentration shocks are preserved rather than
  smeared. `Sr = 0` degenerates exactly to a passive tracer through the same code path, which is what
  makes it usable as a negative control.
- `pile`: the pad, the per-cell lot stacks, and the four reclaim geometries (full face, bucket wheel,
  end, loader) parameterised by the two numbers that decide the layer count, engaged width and reach.
  Provenance fractions on every cut sum to one.
- `stacking`: chevron, windrow, cone shell, chevcon and strata.
- `blending`: tonnage-weighted variance, the variance reduction ratio, the `1/N` independent-layer
  bound, the mixing effect, and experimental variograms with a spherical fit.
- `rtd`: residence-time distribution, its dimensionless variance, and its FIFO/LIFO character.
- `stream`: a correlated truck stream from an exact one-step recursion, with a 32-bit xorshift and
  Box-Muller generator written out explicitly so another language can reproduce it bit for bit.
- 30 tests covering mass conservation, the repose bound, cascade ordering, species-mass conservation,
  the exact `Sr = 0` tracer identity, provenance summing to one across all four reclaim geometries,
  the VRR direction pinned against Loubser and de Korte's published table, and determinism.

### Notes

- The core has no dependencies on purpose. It is plain Python floats and lists, which keeps it
  installable anywhere in seconds and reproducible against a browser implementation.
- `RunConfig.case_id` carries the consumer's label through to the result. The engine never interprets
  it.
