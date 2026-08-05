"""The README is the PyPI front page, so it is checked like code.

WHY THIS EXISTS. The README shipped for three releases describing an engine that no longer existed:
a `PadSpec`/`RunConfig`/`simulate` API where none of those names are defined, a module table naming
`heightfield`, `pile` and `stacking` where none of those modules are on disk, and five stacking
geometries (chevron, windrow, cone shell, chevcon, strata) that the package docstring itself calls a
category error because CONVEYOR STACKERS build those, not trucks.

Nobody caught it because nothing read it. Every other claim in this repo is pinned by a test, and the
one document that strangers actually see was the one document with no gate behind it. That is the same
defect as a documented solver nothing calls, in a different file.
"""
from __future__ import annotations

import pathlib
import re

import pytest

import bedblend

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"


def _text() -> str:
    return README.read_text(encoding="utf-8")


def test_every_module_the_readme_names_exists():
    """The module table may not invent modules, and may not miss the ones that carry the claims."""
    import pkgutil

    table = re.findall(r"^\| `([a-z_]+)`", _text(), re.MULTILINE)
    # The last row groups three modules in one cell, so pick those up too.
    table += re.findall(r"^\| `([a-z_]+)`, `([a-z_]+)`, `([a-z_]+)`", _text(), re.MULTILINE) and \
        list(re.findall(r"`([a-z_]+)`", re.search(r"^\| `[a-z_]+`, .*$", _text(), re.MULTILINE).group(0)))
    named = set(table)
    on_disk = {m.name for m in pkgutil.iter_modules(bedblend.__path__)}

    invented = named - on_disk
    assert not invented, f"the README names modules that do not exist: {sorted(invented)}"

    # The modules that carry the headline claims must be described, or the front page is not a map.
    for required in ("segregation", "facesegregation", "reclaim", "build", "blending"):
        assert required in named, f"the README module table omits `{required}`"


def test_every_bedblend_name_in_the_readme_example_resolves():
    """The quoted example must be runnable, name for name.

    Not executed here, because a build is seconds of CPU and this suite is run on every commit; the
    names are what rot. `PadSpec`, `RunConfig`, `simulate` and `generate_stream` were all quoted in a
    published README and none of the four had existed for three releases.
    """
    blocks = re.findall(r"```python\n(.*?)```", _text(), re.DOTALL)
    assert blocks, "the README carries no python example at all"
    used = set()
    for b in blocks:
        used |= set(re.findall(r"\bbb\.([A-Za-z_][A-Za-z0-9_]*)", b))
    assert used, "the example calls nothing from the package"
    missing = sorted(n for n in used if not hasattr(bedblend, n))
    assert not missing, f"the README example uses names the package does not export: {missing}"


def test_the_readme_does_not_offer_conveyor_geometries():
    """The package docstring calls these a category error; the front page may not sell them.

    Trucks do not build a chevron bed. An earlier version of this library offered chevron, windrow,
    cone shell, chevcon and strata alongside a truck fleet, and the README went on offering them for
    three releases after the engine stopped implementing them.
    """
    body = _text()
    # The disclaimer paragraph names them in order to disown them, so only flag them where they are
    # presented as something the engine DOES.
    disclaimed = body[body.index("It does not model chevron") : body.index("```python")]
    rest = body.replace(disclaimed, "")
    for geometry in ("windrow", "chevcon", "cone shell", "bucket wheel", "bridge reclaimer"):
        assert geometry not in rest.lower(), (
            f"the README offers `{geometry}`, which is conveyor-stacker equipment this engine "
            f"deliberately does not model"
        )


@pytest.mark.parametrize("claim", ["PERCOLATION_COEFFICIENT", "PECLET_DEFAULT"])
def test_the_readme_names_the_anchored_constants_and_they_are_real(claim: str):
    """The honesty section names two anchored coefficients. Both must exist to be anchored."""
    assert claim in _text(), f"the README no longer discloses `{claim}`"
    mod = bedblend.facesegregation if claim == "PERCOLATION_COEFFICIENT" else bedblend.segregation
    assert hasattr(mod, claim), f"`{claim}` is disclosed in the README but not defined"
