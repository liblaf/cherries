from liblaf import cherries


def backend_factory(backend: str | None = None) -> cherries.Backend:
    backend = backend or cherries.env.str("BACKEND", "dummy")
    match backend:
        case "neptune":
            return cherries.BackendNeptune()
        case "dummy":
            return cherries.Backend()
        case _:
            msg: str = f"Unknown backend: {backend}"
            raise ValueError(msg)
