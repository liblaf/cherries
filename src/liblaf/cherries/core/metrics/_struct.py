import array
import datetime

import attrs
import polars as pl


@attrs.define
class Metric:
    """In-memory samples for one scalar metric."""

    name: str
    """Metric name."""

    value: array.array[float] = attrs.field(factory=lambda: array.array("d"))
    """Metric values as doubles."""

    step: array.array[int] = attrs.field(factory=lambda: array.array("L"))
    """Metric steps as unsigned integers."""

    timestamp_ms: array.array[int] = attrs.field(factory=lambda: array.array("Q"))
    """Sample timestamps as milliseconds since the Unix epoch."""

    def append(self, value: float, step: int, time: datetime.datetime) -> None:
        """Append one metric sample."""
        timestamp_ms: int = int(time.timestamp() * 1000)
        self.value.append(value)
        self.step.append(step)
        self.timestamp_ms.append(timestamp_ms)

    def to_polars(self) -> pl.DataFrame:
        """Convert samples to a dataframe with `name`, `value`, `step`, and `time`."""
        df: pl.DataFrame = (
            pl.from_dict(
                {
                    "value": self.value,
                    "step": self.step,
                    "timestamp_ms": self.timestamp_ms,
                },
                {"value": pl.Float64, "step": pl.UInt64, "timestamp_ms": pl.UInt64},
            )
            .with_columns(
                pl.lit(self.name).alias("name"),
                pl.col("timestamp_ms").cast(pl.Datetime("ms")).alias("time"),
            )
            .select("name", "value", "step", "time")
        )
        return df
