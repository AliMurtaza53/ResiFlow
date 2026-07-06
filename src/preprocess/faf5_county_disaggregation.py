"""CLI wrapper for :mod:`nird.faf5_county_disaggregation`."""

try:
    from resiflow.faf5_county_disaggregation import *  # noqa: F401,F403
    from resiflow.faf5_county_disaggregation import main
except ModuleNotFoundError:  # Supports `python -m src.preprocess...` from repo root.
    from src.nird.faf5_county_disaggregation import *  # type: ignore # noqa: F401,F403
    from src.nird.faf5_county_disaggregation import main  # type: ignore


if __name__ == "__main__":
    raise SystemExit(main())
