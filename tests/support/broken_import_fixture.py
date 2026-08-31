"""A module that exists but fails to import, used by one harness self-test.

`require()` must distinguish "the target module does not exist yet" (a written-ahead test,
report it as `NotImplementedYet`) from "a module that does exist is broken" (a real defect,
let it surface). Without this fixture the second branch of that logic is untested, and the
failure mode is the bad one: a genuine import bug reported as "not implemented yet" and
waved through.
"""

import definitely_not_a_real_module_xyz  # noqa: F401
