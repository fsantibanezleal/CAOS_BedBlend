# Architecture

This theme covers how `bedblend`'s seventeen modules become one system, and the two properties that
system is built to guarantee. It is the part of the wiki that answers "why does this run in this
order", as distinct from the methods theme, which answers "what does this compute and where did it
come from".

All three documents below exist. The invariants page is the one to read first if you are about to
change anything in the engine: it lists what the code refuses to let drift and names the function that
enforces each, and two of those exist because an earlier version violated them.

There is one thing worth stating before the documents, because it explains their existence. Every
module in this package does one thing correctly in isolation, and for several releases that was not
enough: `segregation` was complete, tested and called by nothing, while `facesegregation` stood in
with three fitted curves and every document described the equations that were not running. The
composition IS the product, and so it gets its own theme rather than a paragraph in a module
docstring.

The entry point is `bedblend.build`, in `build.py`. What it iterates over is the incoming payload
stream, not the plan: each load is routed to an area, takes the next tip off that area's queue, and
is either placed or recorded as refused. The two-campaign structure comes from the plan rather than
from the loop. `DumpPlan.bench_program` emits, per area and per bench, the whole paddock lattice of
heaps first and then the edge sweeps, one lift at a time up a footprint that shrinks by the
horizontal run of a face at repose. Measured on the repository README's quickstart, bench 0 of the
single area is a programme of 333 tips, 60 paddock followed by 273 edge, strictly in that order.

THE DOZER IS NOT A PHASE BETWEEN THE TWO CAMPAIGNS, and the distinction is worth stating plainly
because the loop reads as though it were one. `_doze` is called from three places and none of them is
a campaign boundary. It runs on a cadence, counted per area, every `DumpPlan.loads_per_dozer_pass`
placed loads (default 12) as an access-only visit that grades the ramp and levels the floor; every
`loads_per_full_pass` (default 60) that visit is instead a full one, adding the crest push and the
safety berm. It runs unscheduled when a load is refused for having no drivable ground, access only,
after which that load is retried; that one is rate-limited by comparing the area's last unscheduled
visit against the GLOBAL load counter, so an area gets at most one every two loads of the whole
stream rather than of its own. And it
runs once per area at the close of the build, access only, because a berm is furniture for a live tip
head and a finished campaign does not have one. Each `DozerPass` record is one blade operation that
actually moved material, so a visit contributes between zero and four of them, and the quickstart's
600 loads produce 221 records.

Reclaim is a separate call, `bedblend.campaign`, which can also be interleaved with the build
through `build`'s `after_load` hook, because plenty of operations feed and draw at the same time and
that produces a different pile from the same ore.

Three couplings distinguish this from a sequence of function calls, and all three are documented in
`01_overview.md`. The pile constrains itself, so every load is routed over the trafficable surface as
it stands at that moment and a tip the pile has grown over is refused and recorded rather than served
anyway. The face decides the shape, so the dump profile is selected from the truck's measured
distance to the live crest and oriented on the crest normal, making the deposit geometry an output of
the build state rather than a setting. And the ledger follows the material, so deposition,
relaxation, dozing and reclaim all carry the block ledger with them.

## Documents

| Document | What it covers |
|---|---|
| [architecture/01_overview.md](architecture/01_overview.md) | The module graph and the build loop: what `build` calls, in what order, per bench and per area, the split between access-only and full dozer visits, why a refused load is a result rather than an error, and where reclaim attaches. |
| [architecture/02_determinism.md](architecture/02_determinism.md) | The seeded stream: one 32-bit xorshift written out explicitly rather than using `random` or numpy, so a browser implementation can reproduce it, what "a run is a pure function of parameters and seed" covers, and the single genuinely stochastic decision in the whole build. |
| [`architecture/03_invariants.md`](architecture/03_invariants.md) | What the engine refuses to let drift: `BlockModel.assert_consistent`, whose `tol_m` defaults to 1e-6 and which fails if the ledger and the terrain disagree by more than that in any column, and `assert_stable`, which raises `ReposeViolation` if any neighbour pair stands more than `STABLE_TOL_DEG` (4.0 degrees) over what the material can hold. |
