# Copyright (c) 2026 liblaf
"""Save as <study>/src/10-run.py; prepare data/mesh.vtu; run python src/10-run.py.

Registered paths stay inside study/data or study/figs. Saved copies are recorded
in run.yaml.artifacts with relative names, SHA-256 digests and byte sizes.
tmp paths stay inside study/tmp and are never saved in a run. For execution
without recording, use DEBUG=1 python src/10-run.py; run returns None.
"""

from pathlib import Path

import pyvista as pv  # ty: ignore[import-not-found]

from liblaf import cherries


class Config(cherries.BaseConfig):
    mesh: Path = cherries.input("mesh.vtu")
    result: Path = cherries.output("result.vtu")


def main(cfg: Config) -> None:
    mesh = pv.read(cfg.mesh)
    mesh.save(cherries.tmp("debug/intermediate.vtu"))
    mesh.save(cfg.result)
    cherries.log_metrics({"points": mesh.n_points, "cells": mesh.n_cells})


if __name__ == "__main__":
    cherries.run(main)
