import array
import datetime

import attrs
import polars as pl


@attrs.define
class Metric:
    name: str
    value: array.array[float] = attrs.field(factory=lambda: array.array("d"))
    step: array.array[int] = attrs.field(factory=lambda: array.array("L"))
    timestamp_ms: array.array[int] = attrs.field(factory=lambda: array.array("Q"))

    def append(self, value: float, step: int, time: datetime.datetime) -> None:
        timestamp_ms: int = int(time.timestamp() * 1000)
        self.value.append(value)
        self.step.append(step)
        self.timestamp_ms.append(timestamp_ms)

    def to_polars(self) -> pl.DataFrame:
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
