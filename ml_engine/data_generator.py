# ml_engine/data_generator.py
#
# Synthetic dataset generation for ML model training.
#
# This module wraps ml_engine.utils.generate_synthetic_training_data() and
# adds convenience CLI usage so you can regenerate training sets without
# importing the full ml_engine package.
#
# Usage (CLI)
# ───────────
#   python -m ml_engine.data_generator              # 2 000 rows → training/eta_training.csv
#   python -m ml_engine.data_generator --n 5000     # custom row count
#   python -m ml_engine.data_generator --seed 99    # reproducible shuffle
#
# Usage (library)
# ───────────────
#   from ml_engine.data_generator import generate_eta_dataset
#   df = generate_eta_dataset(n_samples=3_000, seed=7)

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from ml_engine.utils import generate_synthetic_training_data

logger = logging.getLogger(__name__)

_DEFAULT_OUTPUT = Path(__file__).parent / "training" / "eta_training.csv"


def generate_eta_dataset(
    n_samples: int = 2_000,
    seed: int = 42,
    output_path: Path | str | None = None,
    save: bool = False,
) -> pd.DataFrame:
    """Generate a synthetic ETA training dataset.

    Parameters
    ----------
    n_samples : int
        Number of training rows (default 2 000).
    seed : int
        Random seed for reproducibility.
    output_path : Path, str, or None
        Where to write the CSV.  Defaults to
        ``ml_engine/training/eta_training.csv``.
    save : bool
        When True, persist the DataFrame to *output_path* as CSV.

    Returns
    -------
    pd.DataFrame
        Columns: distance_vehicle_to_source, distance_source_to_dest,
                 vehicle_capacity_kg, vehicle_speed_kmph, traffic_factor,
                 shipment_weight_kg, eta_hours.
    """
    df = generate_synthetic_training_data(n_samples=n_samples, seed=seed)

    if save:
        p = Path(output_path) if output_path else _DEFAULT_OUTPUT
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(p, index=False)
        logger.info("generate_eta_dataset: saved %d rows to %s", len(df), p)

    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Generate synthetic ETA training data")
    parser.add_argument("--n",    type=int, default=2_000, help="Number of rows")
    parser.add_argument("--seed", type=int, default=42,    help="Random seed")
    parser.add_argument("--out",  type=str, default=None,  help="Output CSV path")
    args = parser.parse_args()

    df = generate_eta_dataset(
        n_samples=args.n,
        seed=args.seed,
        output_path=args.out,
        save=True,
    )

    print(f"\n{'─'*50}")
    print(f"  Generated {len(df):,} rows")
    print(f"  ETA  mean={df['eta_hours'].mean():.2f} h  "
          f"min={df['eta_hours'].min():.2f} h  max={df['eta_hours'].max():.1f} h")
    print(f"  Features: {list(df.columns)}")
    print(f"{'─'*50}\n")
