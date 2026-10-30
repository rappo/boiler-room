"""Framework-free core of Boiler Room.

Nothing in this package imports Home Assistant, so it can be unit-tested
with plain `unittest` (see tests/). The HA-facing modules one level up
wire these functions to services, entities and the config flow.
"""
