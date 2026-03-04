# ml_engine/train_eta.py
#
# ETA Model Training Script
#
# Generates synthetic training data, trains a RandomForestRegressor-based
# ETAModel, evaluates it, and saves the fitted model to
# ml_engine/models/eta_model.pkl.
#
# Run
# ───
#   python -m ml_engine.train_eta
#   python -m ml_engine.train_eta --n 5000 --estimators 300
#
# After training the model is automatically used by:
#   - ml_engine/__init__.py::assign_vehicle_ai()
#   - ml_engine/route_optimizer.py::predict_eta()  (loaded via _load_eta_model)

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ml_engine.data_generator import generate_eta_dataset
from ml_engine.eta_model import ETAModel

logger = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).parent / "models" / "eta_model.pkl"


def train(
    n_samples: int = 2_000,
    seed: int = 42,
    n_estimators: int = 200,
    test_size: float = 0.20,
    save_path: Path | str | None = None,
) -> ETAModel:
    """Train the ETA model and save it to disk.

    Parameters
    ----------
    n_samples : int
        Number of synthetic training rows to generate.
    seed : int
        Random seed — controls both data generation and the RF.
    n_estimators : int
        Number of trees in the RandomForestRegressor.
    test_size : float
        Fraction of data held out for evaluation.
    save_path : Path, str, or None
        Destination for the serialised model.
        Defaults to ``ml_engine/models/eta_model.pkl``.

    Returns
    -------
    ETAModel
        Trained model instance (also persisted to disk).
    """
    dest = Path(save_path) if save_path else _MODEL_PATH

    logger.info("── ETA Model Training ──────────────────────────────────────")
    logger.info("  samples     : %d", n_samples)
    logger.info("  seed        : %d", seed)
    logger.info("  n_estimators: %d", n_estimators)
    logger.info("  test_size   : %.0f%%", test_size * 100)
    logger.info("  output      : %s", dest)
    logger.info("────────────────────────────────────────────────────────────")

    # 1. Generate training data
    df = generate_eta_dataset(n_samples=n_samples, seed=seed)
    logger.info("Training dataset: %d rows", len(df))

    # 2. Train model
    model = ETAModel(n_estimators=n_estimators, random_state=seed)
    metrics = model.train(df, test_size=test_size, verbose=True)

    # 3. Save
    model.save(dest)

    # 4. Summary
    print(f"\n{'═'*55}")
    print(f"  ETA Model Training Complete")
    print(f"{'─'*55}")
    print(f"  Training rows  : {len(df):,}")
    print(f"  MAE            : {metrics['mae']:.4f} h")
    print(f"  RMSE           : {metrics['rmse']:.4f} h")
    print(f"  R²             : {metrics['r2']:.4f}")
    print(f"  Saved to       : {dest}")
    print(f"{'═'*55}\n")

    return model


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Train the ETA prediction model")
    parser.add_argument("--n",          type=int,   default=2_000, help="Training samples")
    parser.add_argument("--seed",       type=int,   default=42,    help="Random seed")
    parser.add_argument("--estimators", type=int,   default=200,   help="RF trees")
    parser.add_argument("--test-size",  type=float, default=0.20,  help="Test fraction")
    parser.add_argument("--out",        type=str,   default=None,  help="Output .pkl path")
    args = parser.parse_args()

    train(
        n_samples=args.n,
        seed=args.seed,
        n_estimators=args.estimators,
        test_size=args.test_size,
        save_path=args.out,
    )
