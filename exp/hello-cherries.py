from liblaf import cherries


class Config(cherries.BaseConfig):
    name: str = "world"


@cherries.main()
def main(cfg: Config) -> None:
    ic(f"Hello, {cfg.name}!")


if __name__ == "__main__":
    main(Config())
