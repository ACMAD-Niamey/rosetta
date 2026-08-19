"""Regression tests for issue #5: an unsupported variable must raise a typed,
early error instead of a bare KeyError from deep inside the fetch path.

Requesting a variable a product doesn't carry (e.g. `precip` from
`nmme/spearb`, an SST-only predictor track) used to surface as
`KeyError('precip')` raised by whichever adapter happened to run — after
remote datasets had already been opened. Callers could not distinguish that
*capability* gap from a transient *availability* gap without string-matching
the exception.
"""
import pytest

from rosetta import catalog
from rosetta.errors import VariableNotSupported


# nmme/spearb is the real case from the issue: catalog declares {sst} only.
UNSUPPORTED = ("nmme/spearb", "precip")


def test_fetch_raises_variable_not_supported_instead_of_bare_keyerror():
    import rosetta
    product, variable = UNSUPPORTED
    with pytest.raises(VariableNotSupported):
        rosetta.fetch(product, variable, init="2025-09", target="OND",
                      cache=False, verbose=False)


def test_variable_not_supported_is_a_valueerror():
    """Callers catch ValueError to route config errors apart from data errors."""
    assert issubclass(VariableNotSupported, ValueError)


def test_error_carries_product_variable_and_available():
    """The typed payload is what lets a caller act without string matching."""
    product, variable = UNSUPPORTED
    with pytest.raises(VariableNotSupported) as excinfo:
        catalog.require_variable(product, variable)
    err = excinfo.value
    assert err.product == product
    assert err.variable == variable
    assert err.available == ["sst"]


def test_error_message_names_product_variable_and_available():
    product, variable = UNSUPPORTED
    with pytest.raises(VariableNotSupported) as excinfo:
        catalog.require_variable(product, variable)
    msg = str(excinfo.value)
    assert product in msg and "precip" in msg and "sst" in msg


def test_fetch_validates_before_any_adapter_io(monkeypatch):
    """The whole point of the fix: fail before a byte crosses the network.

    The old behaviour raised only once an adapter was already running, so the
    failure wasted remote opens and arrived too late to be told apart from a
    data-availability problem.
    """
    import sys
    import rosetta
    import rosetta.fetch  # noqa: F401  (rosetta.fetch the *name* is the function)
    fetch_mod = sys.modules["rosetta.fetch"]

    def _boom(*args, **kwargs):
        raise AssertionError("adapter must not be reached for an unsupported variable")

    monkeypatch.setattr(fetch_mod, "get_adapter", _boom)

    product, variable = UNSUPPORTED
    with pytest.raises(VariableNotSupported):
        rosetta.fetch(product, variable, init="2025-09", target="OND",
                      cache=False, verbose=False)


def test_assemble_validates_whole_roster_before_fetching_anything(monkeypatch):
    """A bad model late in the roster must not cost the earlier models' fetches.

    assemble() fans out model by model, so validating only inside fetch() would
    still download every model preceding the unsupported one.
    """
    import sys
    import rosetta.assemble  # noqa: F401  (rosetta.assemble the *name* is the function)
    assemble_mod = sys.modules["rosetta.assemble"]

    calls = []

    def _spy(*args, **kwargs):
        calls.append(args)
        raise AssertionError("fetch must not run for an unvalidated roster")

    monkeypatch.setattr(assemble_mod, "fetch", _spy)

    roster = [
        ("good", "nmme/ccsm4", (2010, 2015)),
        ("bad", "nmme/spearb", (2010, 2015)),   # sst-only -> cannot serve precip
    ]
    with pytest.raises(VariableNotSupported) as excinfo:
        assemble_mod.assemble(roster, "precip", init="2025-09", target="OND")
    assert excinfo.value.product == "nmme/spearb"
    assert calls == []


# ---------------------------------------------------------------------------
# Regression guards: the new check must not reject anything that used to work.
# ---------------------------------------------------------------------------

def test_supported_variable_still_reaches_the_adapter(monkeypatch):
    """The guard must be a capability check, not a new failure mode."""
    import sys
    import rosetta
    import rosetta.fetch  # noqa: F401
    fetch_mod = sys.modules["rosetta.fetch"]

    reached = []

    class _FakeAdapter:
        def fetch_data(self, config, variable, date_range=None, region=None):
            reached.append(variable)
            raise RuntimeError("stop here — we only care that the adapter ran")

    monkeypatch.setattr(fetch_mod, "get_adapter", lambda name: _FakeAdapter())

    with pytest.raises(RuntimeError, match="stop here"):
        rosetta.fetch("nmme/spearb", "sst", init="2025-09", target="OND",
                      cache=False, verbose=False)
    assert reached == ["sst"]


def test_every_catalog_product_accepts_its_own_declared_variables():
    """Guards the helper against mis-reading the catalog's shape."""
    import warnings
    with warnings.catch_warnings():
        # deprecated aliases warn on resolution; that is not what this asserts
        warnings.simplefilter("ignore", DeprecationWarning)
        for product in catalog.list_products():
            for variable in catalog.variables(product):
                catalog.require_variable(product, variable)


def test_no_declared_variable_could_ever_have_been_undeclared():
    """Why the strict check breaks nothing: normalize() has always required a
    declared var_cfg (`product_config["variables"][variable]`), and every
    fetch() result passes through it. So an undeclared variable could never
    have completed a fetch — the check only makes that failure early and typed.
    """
    import inspect
    from rosetta import normalize as normalize_mod
    src = inspect.getsource(normalize_mod.normalize)
    assert 'product_config["variables"][variable]' in src


def test_assemble_with_a_fully_supported_roster_proceeds_to_fetch(monkeypatch):
    import sys
    import rosetta.assemble  # noqa: F401
    assemble_mod = sys.modules["rosetta.assemble"]

    fetched = []

    def _spy(product, variable, **kwargs):
        fetched.append((product, variable))
        raise RuntimeError("stop here — validation let us through")

    monkeypatch.setattr(assemble_mod, "fetch", _spy)

    roster = [("a", "nmme/ccsm4", (2010, 2015)), ("b", "nmme/spearb", (2010, 2015))]
    with pytest.raises(RuntimeError, match="stop here"):
        assemble_mod.assemble(roster, "sst", init="2025-09", target="OND")
    assert fetched == [("nmme/ccsm4", "sst")]


def test_product_with_no_variables_block_reports_no_variables():
    with pytest.raises(VariableNotSupported) as excinfo:
        catalog.require_variable("fake/empty", "precip", config={})
    assert excinfo.value.available == []
    assert "no variables" in str(excinfo.value)


def test_assemble_precheck_defers_unknown_products_to_fetch(monkeypatch):
    """The roster precheck is a capability check, not a product-existence check.

    An id that isn't in the catalog at all has always been fetch()'s error to
    raise; the precheck must not turn that into a new, earlier failure mode
    (it would break callers who stub fetch() out entirely).
    """
    import sys
    import rosetta.assemble  # noqa: F401
    assemble_mod = sys.modules["rosetta.assemble"]

    reached = []
    monkeypatch.setattr(assemble_mod, "fetch",
                        lambda product, variable, **kw: reached.append(product) or
                        (_ for _ in ()).throw(RuntimeError("fetch reached")))

    with pytest.raises(RuntimeError, match="fetch reached"):
        assemble_mod.assemble([("A", "nmme/definitely-not-a-product", (1993, 1995))],
                              "precip", init="2026-01", target="MAM")
    assert reached == ["nmme/definitely-not-a-product"]
