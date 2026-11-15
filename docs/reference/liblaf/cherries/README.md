# Python API

Normal recording returns a directory under
`<repo>/cherries/runs/YYYY/mm/dd/<UUIDv7>/`. The date is the original local date
in the persisted `run.yaml` `start-time`; finishing after midnight or transferring
across timezones keeps the same partition. See the [storage design](../../../design/cherries/storage.md).

::: liblaf.cherries
