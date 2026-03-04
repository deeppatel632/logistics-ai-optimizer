# ml_engine/eta_model.py
#
# RandomForest-based ETA (Estimated Time of Arrival) Prediction Model.
#
# Architecture
# ────────────
# Input  : 6-dimensional feature vector (see ml_engine.utils.FEATURE_COLUMNS)
# Target : eta_hours  — continuous float, travel time in hours
# Model  : sklearn RandomForestRegressor with 200 estimators
#          (good out-of-the-box bias-variance balance; no hyperparameter
#          tuning required for the logistics-routing scale)
#
# Usage
# ─────
# Training:
#   from ml_engine.eta_model import ETAModel
#   model = ETAModel()
#   model.train(train_df)               # df has FEATURE_COLUMNS + "eta_hours"
#   model.save("ml_engine/models/eta_model.pkl")
#
# Inference:
#   model = ETAModel.load("ml_engine/models/eta_model.pkl")
#   eta = model.predict(feature_array)  # np.ndarray shape (1, 6)
#
# The preferred high-level entry point is assign_vehicle_ai() in __init__.py
# which handles feature construction from raw shipment / vehicle dicts.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml_engine.utils import FEATURE_COLUMNS, load_model, save_model

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_PATH = Path(__file__).parent / "models" / "eta_model.pkl"

# ---------------------------------------------------------------------------
# Heuristic fallback (used when no trained model exists)
# ---------------------------------------------------------------------------

_FALLBACK_SPEED_KMPH = 80.0


def _heuristic_eta(feature_row: np.ndarray) -> float:
    """Compute a physics-based ETA when the RF model is not available.

    Uses: (dist_v_to_src + dist_src_to_dst) / (speed × traffic_factor)

    Feature column indices match FEATURE_COLUMNS:
      0 — distance_vehicle_to_source   (km)
      1 — distance_source_to_dest      (km)
      2 — vehicle_capacity_kg          (unused in heuristic)
      3 — vehicle_speed_kmph           (km/h)
      4 — traffic_factor               (0-1)
      5 — shipment_weight_kg           (unused in heuristic)
    """
    row = feature_row.ravel()
    total_dist = row[0] + row[1]
    eff_speed  = max(row[3] * row[4], 1.0)
    return round(max(total_dist / eff_speed, 0.1), 3)


# ---------------------------------------------------------------------------
# ETAModel
# ---------------------------------------------------------------------------

class ETAModel:
    """Trained RandomForest ETA predictor.

    The model is wrapped in a ``Pipeline`` so the scaler and estimator are
    always bundled together — saving/loading one pickle handles both.

    Attributes
    ----------
    pipeline : sklearn.pipeline.Pipeline or None
        Fitted pipeline (StandardScaler → RandomForestRegressor).
        ``None`` until :meth:`train` has been called.
    is_trained : bool
        True after a successful :meth:`train` call.
    feature_importances_ : dict[str, float] or None
        Feature name → importance after training.
    """

    def __init__(
        self,
        n_estimators: int = 200,
        max_depth: Optional[int] = None,
        min_samples_leaf: int = 3,
        random_state: int = 42,
    ) -> None:
        self.pipeline: Optional[Pipeline] = None
        self.is_trained: bool = False
        self.feature_importances_: Optional[Dict[str, float]] = None

        self._rf_kwargs = {
            "n_estimators":    n_estimators,
            "max_depth":       max_depth,
            "min_samples_leaf": min_samples_leaf,
            "random_state":    random_state,
            "n_jobs":          -1,
        }

    # ── Training ──────────────────────────────────────────────────────────

    def train(
        self,
        df: pd.DataFrame,
        test_size: float = 0.2,
        verbose: bool = True,
    ) -> Dict[str, float]:
        """Fit the model on a labelled DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain all :data:`~ml_engine.utils.FEATURE_COLUMNS` plus
            an ``eta_hours`` target column.
        test_size : float
            Fraction held out for evaluation (default 0.20).
        verbose : bool
            Log evaluation metrics to INFO level.

        Returns
        -------
        dict
            ``{"mae": ..., "rmse": ..., "r2": ...}`` on the test split.

        Raises
        ------
        ValueError
            If required columns are missing from ``df``.
        """
        required = set(FEATURE_COLUMNS) | {"eta_hours"}
        missing  = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame is missing columns: {missing}")

        X = df[FEATURE_COLUMNS].values.astype(np.float64)
        y = df["eta_hours"].values.astype(np.float64)

        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=test_size, random_state=42
        )

        self.pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("rf",     RandomForestRegressor(**self._rf_kwargs)),
        ])
        self.pipeline.fit(X_tr, y_tr)
        self.is_trained = True

        # Feature importances (from the RF, pre-scaling so still meaningful)
        rf = self.pipeline.named_steps["rf"]
        self.feature_importances_ = dict(zip(FEATURE_COLUMNS, rf.feature_importances_))

        metrics = self._evaluate(X_te, y_te)

        if verbose:
            logger.info(
                "ETAModel trained — n=%d  MAE=%.3f h  RMSE=%.3f h  R²=%.4f",
                len(df), metrics["mae"], metrics["rmse"], metrics["r2"],
            )
            for feat, imp in sorted(
                self.feature_importances_.items(), key=lambda t: -t[1]
            ):
                logger.info("  %-36s %.4f", feat, imp)

        return metrics

    def _evaluate(self, X: np.ndarray, y: np.ndarray) -> Dict[str, float]:
        assert self.pipeline is not None
        y_pred = self.pipeline.predict(X)
        return {
            "mae":  round(float(mean_absolute_error(y, y_pred)), 4),
            "rmse": round(float(np.sqrt(mean_squared_error(y, y_pred))), 4),
            "r2":   round(float(r2_score(y, y_pred)), 4),
        }

    # ── Inference ─────────────────────────────────────────────────────────

    def predict(self, features: np.ndarray) -> float:
        """Predict ETA in hours for one feature vector.

        Parameters
        ----------
        features : np.ndarray
            Shape ``(1, 6)`` float64 array with columns in :data:`FEATURE_COLUMNS`
            order.  Use :func:`~ml_engine.utils.build_feature_vector` to
            construct this from raw vehicle / shipment dicts.

        Returns
        -------
        float
            Predicted ETA in hours, bounded to [0.1, ∞).
            Falls back to the physics heuristic when the model is not trained.
        """
        if not self.is_trained or self.pipeline is None:
            logger.debug("ETAModel.predict: not trained — using heuristic")
            return _heuristic_eta(features)
        try:
            eta = float(self.pipeline.predict(features)[0])
            return round(max(eta, 0.1), 3)
        except Exception as exc:
            logger.warning("ETAModel.predict failed (%s) — falling back to heuristic", exc)
            return _heuristic_eta(features)

    def predict_batch(self, X: np.ndarray) -> np.ndarray:
        """Predict ETAs for multiple rows at once.

        Parameters
        ----------
        X : np.ndarray, shape (n, 6)
            Feature matrix for *n* vehicles.

        Returns
        -------
        np.ndarray, shape (n,)
            Predicted ETA in hours per row.
        """
        if not self.is_trained or self.pipeline is None:
            return np.array([_heuristic_eta(X[i:i+1]) for i in range(len(X))])
        return np.maximum(self.pipeline.predict(X), 0.1)

    # ── Persistence ───────────────────────────────────────────────────────

    def save(self, path: Optional[Path | str] = None) -> None:
        """Pickle the entire ETAModel instance to *path*.

        Parameters
        ----------
        path : Path, str, or None
            Destination file.  Defaults to
            ``ml_engine/models/eta_model.pkl``.
        """
        save_model(self, path or _DEFAULT_MODEL_PATH)

    @classmethod
    def load(cls, path: Optional[Path | str] = None) -> "ETAModel":
        """Load a previously saved ETAModel from *path*.

        Returns a **new untrained** instance (with heuristic fallback) if
        the file does not exist or cannot be deserialized.

        Parameters
        ----------
        path : Path, str, or None
            Source file.  Defaults to ``ml_engine/models/eta_model.pkl``.
        """
        target = Path(path) if path else _DEFAULT_MODEL_PATH
        loaded = load_model(target)
        if isinstance(loaded, cls):
            return loaded
        logger.info("ETAModel.load: no saved model at %s — using fresh instance", target)
        return cls()

    def __repr__(self) -> str:
        status = f"trained, MAE≈{self.feature_importances_ and '—'}" if self.is_trained else "untrained"
        return f"ETAModel(n_estimators={self._rf_kwargs['n_estimators']}, {status})"
