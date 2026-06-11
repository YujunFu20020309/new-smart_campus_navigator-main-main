"""Create a review preview that combines verified places with pending places.

By default this tool does not modify data/places.csv. It writes a preview CSV
so pending map-clicked places can be reviewed before a human merges them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_admin import PENDING_PLACE_COLUMNS, load_pending_places
from src.utils import ensure_place_visibility_columns, load_places


DEFAULT_PLACES_PATH = PROJECT_ROOT / "data" / "places.csv"
DEFAULT_PENDING_PATH = PROJECT_ROOT / "data" / "manual_places_pending.csv"
DEFAULT_PREVIEW_PATH = PROJECT_ROOT / "data" / "places_with_pending_preview.csv"


def build_pending_preview(
    places_path: str | Path = DEFAULT_PLACES_PATH,
    pending_path: str | Path = DEFAULT_PENDING_PATH,
    preview_path: str | Path = DEFAULT_PREVIEW_PATH,
) -> pd.DataFrame:
    """Write and return a places + pending preview without changing places.csv."""
    places_df = ensure_place_visibility_columns(load_places(places_path)).copy()
    pending_df = load_pending_places(pending_path)

    columns = list(places_df.columns)
    for column in PENDING_PLACE_COLUMNS:
        if column not in columns:
            columns.append(column)
    for frame in (places_df, pending_df):
        for column in columns:
            if column not in frame.columns:
                frame[column] = ""

    preview_df = pd.concat(
        [places_df.loc[:, columns], pending_df.loc[:, columns]],
        ignore_index=True,
    ).fillna("")
    Path(preview_path).parent.mkdir(parents=True, exist_ok=True)
    preview_df.to_csv(preview_path, index=False, encoding="utf-8-sig")
    return preview_df


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate data/places_with_pending_preview.csv for manual review. "
            "This does not modify data/places.csv."
        )
    )
    parser.add_argument("--places", default=str(DEFAULT_PLACES_PATH))
    parser.add_argument("--pending", default=str(DEFAULT_PENDING_PATH))
    parser.add_argument("--output", default=str(DEFAULT_PREVIEW_PATH))
    args = parser.parse_args()

    preview_df = build_pending_preview(args.places, args.pending, args.output)
    print(f"Wrote preview: {args.output}")
    print(f"Rows: {len(preview_df)}")
    print("data/places.csv was not modified.")


if __name__ == "__main__":
    main()
