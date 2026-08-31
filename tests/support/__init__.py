"""Test-harness support code (TS-00).

Test plan §8.1 names the contents of this package as one of three things that must exist
before most of the plan can be written: the socket guard, the store spy, the injected
`Clock` and seeded `Random`, and the wiring that binds `RecordedFixtureProvider` in the
fast tier.

This is harness code, not test code: it ships green and is covered by
`tests/unit/harness/test_harness.py`.
"""
