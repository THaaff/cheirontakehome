# Package marker so this directory's ``conftest.py`` is imported as
# ``transform.conftest`` rather than the bare module name ``conftest``. Without
# it, pytest's prepend import mode would register two top-level ``conftest``
# modules (here and in tests/contracts), and the contracts suite's runtime
# ``from conftest import ...`` would resolve to the wrong one.
