"""add ml_features table

Revision ID: a1b2c3d4e5f6
Revises: 7e03a46c453f
Create Date: 2026-03-04 12:00:00.000000

Creates the `ml_features` table used by the Feature Store (Step 48).

Schema design decisions:
  • Composite PRIMARY KEY (entity_id, feature_name) — enforces uniqueness
    per entity/feature pair and provides a covering index for the most common
    lookup pattern.
  • FLOAT for value — sufficient precision for all current features
    (speed, distance, traffic score, delivery delay).  For higher-precision
    needs, switch to NUMERIC(18,6).
  • updated_at / created_at — allow training jobs to export only changed
    features since the last export ("changed since" query pattern).
  • ix_ml_features_entity_id index — speeds up load-all-features-for-entity
    queries used by get_feature_vector().
  • ix_ml_features_updated_at index — speeds up time-ranged training exports.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '7e03a46c453f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the ml_features table."""
    op.create_table(
        'ml_features',

        # ----------------------------------------------------------------
        # Primary key: composite on (entity_id, feature_name).
        # Covers the most common access pattern:
        #   WHERE entity_id = ? AND feature_name = ?
        # ----------------------------------------------------------------
        sa.Column(
            'entity_id',
            sa.String(length=200),
            nullable=False,
            comment=(
                "Identifier for the entity this feature belongs to. "
                "Examples: 'TRUCK_102', 'ROUTE_77', 'WH_5'."
            ),
        ),
        sa.Column(
            'feature_name',
            sa.String(length=200),
            nullable=False,
            comment=(
                "Feature name. Well-known values: vehicle_speed, "
                "traffic_score, route_distance, delivery_delay, "
                "on_time_rate, vehicle_load_ratio."
            ),
        ),

        # ----------------------------------------------------------------
        # Feature value — stored as FLOAT.
        # ----------------------------------------------------------------
        sa.Column(
            'value',
            sa.Float(),
            nullable=False,
            comment="Numeric feature value (ordinal-encode categoricals before storing).",
        ),

        # ----------------------------------------------------------------
        # Timestamps for audit + incremental training exports.
        # ----------------------------------------------------------------
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            comment="Timestamp of the most recent write.  Used for incremental training exports.",
        ),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            comment="Timestamp of the first write.  Immutable after insert.",
        ),

        # ----------------------------------------------------------------
        # Composite primary key — enforces uniqueness and is also the
        # most efficient index for point lookups.
        # ----------------------------------------------------------------
        sa.PrimaryKeyConstraint('entity_id', 'feature_name'),
    )

    # Secondary index on entity_id alone for get_feature_vector() queries:
    #   SELECT feature_name, value
    #   FROM   ml_features
    #   WHERE  entity_id = ?
    #   AND    feature_name IN (…)
    op.create_index(
        'ix_ml_features_entity_id',
        'ml_features',
        ['entity_id'],
        unique=False,
    )

    # Index on updated_at for incremental training exports:
    #   SELECT * FROM ml_features WHERE updated_at >= :last_export_time
    op.create_index(
        'ix_ml_features_updated_at',
        'ml_features',
        ['updated_at'],
        unique=False,
    )


def downgrade() -> None:
    """Drop the ml_features table and its indexes."""
    op.drop_index('ix_ml_features_updated_at', table_name='ml_features')
    op.drop_index('ix_ml_features_entity_id',  table_name='ml_features')
    op.drop_table('ml_features')
