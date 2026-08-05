# Guides

This theme is the practical half of the wiki: getting the package installed, getting a build to run,
replacing the synthetic scenario with your own ground and your own material, and knowing where the
model stops being defensible. The methods theme tells you what a computation means; these pages tell
you how to drive it and when not to believe it.

Installation is genuinely trivial and that is a design decision rather than an accident. The core
declares no dependencies at all, requires Python 3.10 or newer, and is plain floats and lists rather
than numpy, because it has to be reproducible bit for bit against a browser implementation of the
same equations and because a dependency-free core installs anywhere in seconds. `pip install
bedblend` is the whole procedure.

What is not trivial is the run time, and it is better to know that before your first build than
during it. The quickstart in the repository `README.md` is a 60 by 60 cell pad at 2.5 m cells taking
600 loads. Measured on the development machine over four runs, the build took 63 to 68 seconds, mean
65, and the 24-cut reclaim campaign took 1.6 seconds. Read those as an order of magnitude rather than
a benchmark: they are single-threaded pure Python on one machine, and nobody has profiled this across
pad sizes. What is structural rather than incidental is that `build` calls `reachable_mask` over the
whole pad once per load, which is what makes the pile constrain its own construction and is the term
that grows with both the load count and the cell count. Nothing in the package is asynchronous or
parallel, it imports nothing outside the standard library, and it prints nothing, so a build that
looks hung is usually just working.

Expect refusals, and read them as a result rather than a fault. In that same quickstart, 480 of 600
loads were placed and 120 were refused, a 20.0 percent refusal rate, and the profile census came out
118 paddock, 207 oval, 96 comet and 59 rectangular across 221 dozer passes. A refused load is the
model reporting that the plan asked for something the pile no longer allows, and the count of them is
a real measure of how good the dump plan was. `BuildResult.refused` carries each one with its reason
attached.

One caller error is worth naming here because it is the one that produces the most confusing failure.
If the shovel is placed inside a dump area's footprint, `build` raises `ValueError` immediately and
says so, because the first load placed there would bury the loading point and every later load would
be refused for having no drivable start. That check exists so the symptom does not have to be
diagnosed from a build that placed one load and refused five hundred and ninety-nine.

## Documents

All three are written and on disk. This page said the opposite until the three files landed, which is
the same defect the release itself was about, so it is worth saying plainly here: the sentence that
used to sit in this paragraph, "NONE OF THE THREE HAS BEEN WRITTEN. There is no `guides/` directory on
disk", was true when it was written and false the moment the directory appeared, and nothing gated it.
Every quoted number in the three is produced by running the engine at `0.07.002`, not recalled.

| Document | What it covers |
|---|---|
| [`guides/01_install-and-quickstart.md`](guides/01_install-and-quickstart.md) | Installing from PyPI, the smallest complete script that builds a pile and reclaims it, what each object in that script is, and how to read the placed, refused, profile-census and VRR numbers it prints. |
| [`guides/02_use-on-your-own-data.md`](guides/02_use-on-your-own-data.md) | Replacing the synthetic scenario: real survey ground through `Terrain.from_ground`, your own `Material`, a `DumpPlan` that is not a rectangular yard, a load stream from your own dig sequence, and the `route` callable that sends each class to its own area. |
| [`guides/03_calibration-and-limits.md`](guides/03_calibration-and-limits.md) | Which constants are anchored rather than measured and what would replace each, the solver settings that are numerical rather than physical, the regimes where the solver and the published sources part company, and the failure modes to expect outside the evidence. |

## Related reference

[`data-contract.md`](data-contract.md) is the page to keep open beside guide 02. It specifies the
shapes crossing the boundary, what `build` consumes and what a `LoadRecord`, a `BuildResult`, a
`Parcel` and a `Cut` contain, every field with its unit and default enumerated from
`dataclasses.fields` rather than by eye, so a consuming application knows what it may rely on. It also
states what happens to bad input: which cases raise, which clamp, and which are recorded as a refusal
with a reason.

## Before you record a result

Two habits save more time than they cost, and both come from defects this repository has actually
shipped.

Rebuild the packaging metadata before you log an engine version alongside a result.
`bedblend.__version__` is read from `importlib.metadata`, not from a literal, which was the right fix
for a literal that had drifted two releases behind. The consequence is that in a development checkout
the reported version is whatever metadata the interpreter happens to find. Measured at the time of
writing, the source tree declared `0.07.002` while `__version__` reported `0.7.1` from the repository
root and `0.5.0` from any other directory, in the same environment, because a stale source-root
`egg-info` shadows the installed distribution. A clean install from PyPI does not have this problem.

Turn `verify_every` on whenever a build looks wrong. `build` accepts `verify_every: int`, off by
default because the check is O(cells), which reconciles the block ledger against the terrain every N
loads and fails loudly at the first disagreement over `BlockModel.assert_consistent`'s `tol_m` of
1e-6 m rather than letting every grade downstream be quietly wrong. One test file turns it on:
`tests/test_build.py` builds with `verify_every=50` and every test in that file shares that build.
The other place the package `build` is called from a test, `tests/test_topography.py`, leaves it off,
so "the suite runs with it on" would be too strong. Note also that `build` always calls
`model.assert_consistent(terrain)` once at the end regardless, so a build that returns at all has
been reconciled once; `verify_every` is what tells you WHICH load broke it.

The full suite is 137 tests across eleven files and takes about 85 seconds, over half of that in
three tests in `tests/test_build.py` that run end-to-end builds.
