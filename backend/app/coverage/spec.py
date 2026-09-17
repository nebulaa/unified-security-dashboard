"""Metric catalog — the three layers rendered on /executive.

`item_type` names the inventory the metric divides by (its Y); `signal` names the
key a collector sets on an item when the control is in place (its X). Secondaries
are supporting figures shown under a tile: they use the same X/Y machinery but
never carry a RAG colour, because they are not the commitment being measured.
"""

from __future__ import annotations

from dataclasses import dataclass

ITEM_CLOUD_ACCOUNT = "cloud_account"
ITEM_CLUSTER = "cluster"
ITEM_VM = "vm"
ITEM_REPO = "repo"
ITEM_LAUNCH_TEMPLATE = "launch_template"


@dataclass(frozen=True)
class SecondarySpec:
    """Supporting X/Y line under a tile. No RAG."""

    key: str
    label: str
    item_type: str
    signal: str
    unit: str
    # When false the secondary divides by every item of its type, not just the
    # in-scope ones — that is how "all environments (incl. non-prod)" is built.
    in_scope_only: bool = True


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    definition: str
    item_type: str
    signal: str
    unit: str
    secondary: SecondarySpec | None = None


@dataclass(frozen=True)
class LayerSpec:
    key: str
    label: str
    scope: str
    metrics: tuple[MetricSpec, ...]


LAYERS: tuple[LayerSpec, ...] = (
    LayerSpec(
        key="platform",
        label="Platform",
        scope="Cloud accounts and control plane · production scope",
        metrics=(
            MetricSpec(
                key="wiz_connector",
                label="Wiz coverage",
                definition="Production cloud accounts with a healthy Wiz connector",
                item_type=ITEM_CLOUD_ACCOUNT,
                signal="wiz_connector",
                unit="production accounts",
                secondary=SecondarySpec(
                    key="wiz_connector_all_env",
                    label="All environments (incl. non-prod)",
                    item_type=ITEM_CLOUD_ACCOUNT,
                    signal="wiz_connector",
                    unit="accounts",
                    in_scope_only=False,
                ),
            ),
            MetricSpec(
                key="threat_detection",
                label="Threat detection",
                definition="Prod accounts with cloud events flowing into Wiz Defend (last 24h)",
                item_type=ITEM_CLOUD_ACCOUNT,
                signal="wiz_defend_24h",
                unit="production accounts",
            ),
            MetricSpec(
                key="forensics_readiness",
                label="Forensics readiness",
                definition="Prod accounts with evidence-collection role deployed and validated",
                item_type=ITEM_CLOUD_ACCOUNT,
                signal="forensics_role_validated",
                unit="production accounts",
            ),
        ),
    ),
    LayerSpec(
        key="workload",
        label="Workload",
        scope="Running compute · production scope",
        metrics=(
            MetricSpec(
                key="runtime_k8s",
                label="Runtime protection — Kubernetes",
                definition=(
                    "Prod clusters with a healthy Wiz Runtime Sensor reporting in the last 7 days"
                ),
                item_type=ITEM_CLUSTER,
                signal="runtime_sensor_7d",
                unit="clusters",
            ),
            MetricSpec(
                key="runtime_vm",
                label="Runtime protection — VMs",
                definition=(
                    "Running prod instances (>24h old, EC2 + GCE) with sensor installed "
                    "and reporting"
                ),
                item_type=ITEM_VM,
                signal="runtime_sensor_reporting",
                unit="instances",
                secondary=SecondarySpec(
                    key="sensor_in_launch_templates",
                    label="Sensor in golden AMI / launch templates",
                    item_type=ITEM_LAUNCH_TEMPLATE,
                    signal="sensor_baked",
                    unit="templates",
                ),
            ),
        ),
    ),
    LayerSpec(
        key="code",
        label="Code",
        scope="Eligible repos: non-archived, non-fork, active in last 90 days",
        metrics=(
            MetricSpec(
                key="sonar",
                label="Sonar scan coverage",
                definition="Eligible repos analyzed by SonarCloud in the last 30 days",
                item_type=ITEM_REPO,
                signal="sonar_analyzed_30d",
                unit="repos covered",
            ),
            MetricSpec(
                key="dependabot",
                label="Dependabot coverage",
                definition="Eligible repos with Dependabot alerts enabled",
                item_type=ITEM_REPO,
                signal="dependabot_enabled",
                unit="repos covered",
                secondary=SecondarySpec(
                    key="dependabot_version_updates",
                    label="Version updates configured (dependabot.yml)",
                    item_type=ITEM_REPO,
                    signal="dependabot_version_updates",
                    unit="repos",
                ),
            ),
        ),
    ),
)

# Columns on the key-project matrix. `runtime` is a blend of the two workload
# metrics: one cell, weighted by item count, with both raw ratios in its note.
RUNTIME_COLUMN_KEY = "runtime"
RUNTIME_BLEND_METRICS: tuple[str, ...] = ("runtime_k8s", "runtime_vm")

PROJECT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("wiz_connector", "Platform — Wiz (prod)"),
    (RUNTIME_COLUMN_KEY, "Workload — Runtime"),
    ("sonar", "Code — Sonar"),
    ("dependabot", "Code — Dependabot"),
)

_COLUMNS_BY_LAYER: dict[str, tuple[tuple[str, str], ...]] = {
    "platform": (("wiz_connector", "Platform — Wiz (prod)"),),
    "workload": ((RUNTIME_COLUMN_KEY, "Workload — Runtime"),),
    "code": (("sonar", "Code — Sonar"), ("dependabot", "Code — Dependabot")),
}


def project_columns_for(enabled_layers: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    return tuple(
        column
        for layer in enabled_layers
        for column in _COLUMNS_BY_LAYER.get(layer, ())
    )

# Item types that a key project claims through its cloud mapping vs its code
# mapping. Kept explicit because the two joins are deliberately different.
PROJECT_CLOUD_ITEM_TYPES: frozenset[str] = frozenset(
    {ITEM_CLOUD_ACCOUNT, ITEM_CLUSTER, ITEM_VM}
)
PROJECT_CODE_ITEM_TYPES: frozenset[str] = frozenset({ITEM_REPO})

_METRICS_BY_KEY: dict[str, MetricSpec] = {
    metric.key: metric for layer in LAYERS for metric in layer.metrics
}


def metric_keys() -> tuple[str, ...]:
    return tuple(_METRICS_BY_KEY)


def get_metric(key: str) -> MetricSpec:
    try:
        return _METRICS_BY_KEY[key]
    except KeyError:
        raise KeyError(f"unknown coverage metric: {key}") from None
