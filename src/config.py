"""Config — all cluster details from .env, all knobs with spec defaults.

REQ-013 (configurable pace), design §8 defaults. Nothing hardcoded (NFR-2).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    # Cluster (from .env — connect-workshop.sh wrote it)
    wxd_host: str = os.environ.get("WXD_HOST", "")
    presto_host: str = os.environ.get("PRESTO_HOST", "")
    cassandra_host: str = os.environ.get("CASSANDRA_HOST", "")
    cassandra_port: int = int(os.environ.get("CASSANDRA_PORT", "443"))
    user: str = os.environ.get("WORKSHOP_USER", "")
    password: str = os.environ.get("WORKSHOP_PASSWORD", "")
    suffix: str = os.environ.get("WORKSHOP_SCHEMA_SUFFIX", "")

    # Session knobs (design §8; overridable via env for the demo)
    tick_seconds: float = float(os.environ.get("TICK_SECONDS", "5"))
    lookback_days: int = int(os.environ.get("LOOKBACK", "90"))
    shortlist_size: int = int(os.environ.get("SHORTLIST", "3"))
    risk_per_trade_pct: float = float(os.environ.get("RISK_PCT", "1.0"))
    max_aggregate_risk_pct: float = float(os.environ.get("AGG_RISK_PCT", "3.0"))
    max_open_positions: int = int(os.environ.get("MAX_POSITIONS", "5"))
    # REQ-019 per-asset-class share of aggregate open risk (percent)
    class_risk_caps: Dict[str, float] = field(
        default_factory=lambda: {"default": 50.0, "crypto": 30.0})

    # Presto catalog name for the Cassandra connector on this cluster
    cassandra_catalog: str = os.environ.get("CASSANDRA_CATALOG",
                                            "cassandra_catalog")

    @property
    def keyspace(self) -> str:
        return f"financial_{self.suffix}"          # e.g. financial_user31

    @property
    def federated_keyspace(self) -> str:
        """The Cassandra keyspace as Presto sees it (B1, §4.6)."""
        return f"{self.cassandra_catalog}.{self.keyspace}"

    @property
    def iceberg_schema(self) -> str:
        return f"iceberg_data.financial_{self.suffix}"

    @property
    def reference_schema(self) -> str:
        return "iceberg_data.financial_reference"

    def class_cap(self, asset_class: str) -> float:
        return self.class_risk_caps.get(asset_class, self.class_risk_caps["default"])


settings = Settings()

if __name__ == "__main__":
    s = settings
    safe = {k: ("***" if "password" in k else v) for k, v in vars(s).items()}
    print(safe, "\nkeyspace:", s.keyspace, "\niceberg:", s.iceberg_schema)
