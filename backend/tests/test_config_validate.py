"""Config cross-check gate — must fail closed on deliberate drift."""

from __future__ import annotations

from pathlib import Path

from app.core.component_sources import ComponentRow, load_component_map_rows
from app.core.config_store import OwnershipMap, TeamConfig
from app.core.config_validate import (
    default_paths,
    validate_all,
    validate_component_rows,
    validate_terraform_github_org,
    validate_wiz_service_catalog_live,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_config_validate_passes_on_repo_config() -> None:
    config_dir, repo_root = default_paths()
    result = validate_all(config_dir=config_dir, repo_root=repo_root)
    assert result.ok, result.errors


def test_ingest_alignment_fails_when_teams0_disagrees() -> None:
    ownership = OwnershipMap(
        asset_to_team={"repo:ExampleOrg/product-core": "order"},
        teams={
            "offer": TeamConfig(name="offer"),
            "order": TeamConfig(name="order"),
        },
    )
    row = ComponentRow(
        service="NDCGatewayService",
        repo="product-core",
        teams=("offer", "order"),
        sonar_projects=("ExampleOrg_product-core",),
        application_key="ndc-gateway",
        source="master",
    )
    result = validate_component_rows(ownership, [row], label="test")
    assert not result.ok
    assert "teams[0]='offer'" in result.errors[0]
    assert "stamps 'order'" in result.errors[0]


def test_component_map_rows_load() -> None:
    rows = load_component_map_rows(REPO_ROOT)
    assert rows


# ---------- validate_terraform_github_org ----------

_VAR_BLOCK_DEFAULT_ExampleOrgINC = '''
variable "project_id" {
  type    = string
  default = "example-lab-project"
}

variable "github_org" {
  description = "GitHub organisation polled by the Dependabot poller."
  type        = string
  default     = "ExampleOrg"
}
'''

_VAR_BLOCK_DEFAULT_EMPTY = '''
variable "github_org" {
  type    = string
  default = ""
}
'''

_VAR_BLOCK_NO_DEFAULT = '''
variable "github_org" {
  type = string
}
'''


def _write_tf_dir(tmp_path: Path, *, variables_tf: str | None, tfvars: dict[str, str]) -> Path:
    tf_dir = tmp_path / "terraform"
    tf_dir.mkdir(parents=True)
    if variables_tf is not None:
        (tf_dir / "variables.tf").write_text(variables_tf, encoding="utf-8")
    for name, body in tfvars.items():
        (tf_dir / name).write_text(body, encoding="utf-8")
    return tf_dir


def test_terraform_github_org_passes_with_non_empty_default(tmp_path: Path) -> None:
    """Default `ExampleOrg`, no tfvars overrides — every env resolves canonically."""
    tf_dir = _write_tf_dir(
        tmp_path,
        variables_tf=_VAR_BLOCK_DEFAULT_ExampleOrgINC,
        tfvars={
            "stage.tfvars": 'project_id = "example-lab-project"\n',
            "prod.tfvars": 'project_id = "example-security-project"\n',
        },
    )
    result = validate_terraform_github_org(tf_dir)
    assert result.ok, result.errors


def test_terraform_github_org_fails_when_tfvars_override_is_empty(tmp_path: Path) -> None:
    """An explicit `github_org = ""` in tfvars masks the canonical default
    and would silently produce lowercase asset_ids in that environment.
    """
    tf_dir = _write_tf_dir(
        tmp_path,
        variables_tf=_VAR_BLOCK_DEFAULT_ExampleOrgINC,
        tfvars={
            "stage.tfvars": 'project_id = "example-lab-project"\n',
            "prod.tfvars": 'project_id = "example-security-project"\ngithub_org = ""\n',
        },
    )
    result = validate_terraform_github_org(tf_dir)
    assert not result.ok
    assert len(result.errors) == 1
    assert "prod.tfvars" in result.errors[0]
    assert "empty string" in result.errors[0]


def test_terraform_github_org_fails_when_default_empty_and_no_override(tmp_path: Path) -> None:
    """Default of `""` with no tfvars override leaves every env effectively
    unset.
    """
    tf_dir = _write_tf_dir(
        tmp_path,
        variables_tf=_VAR_BLOCK_DEFAULT_EMPTY,
        tfvars={"stage.tfvars": 'project_id = "example-lab-project"\n'},
    )
    result = validate_terraform_github_org(tf_dir)
    assert not result.ok
    assert "stage.tfvars" in result.errors[0]
    assert "no non-empty default" in result.errors[0]


def test_terraform_github_org_passes_when_tfvars_overrides_empty_default(tmp_path: Path) -> None:
    """Default empty, but a tfvars file overrides explicitly — that env is fine."""
    tf_dir = _write_tf_dir(
        tmp_path,
        variables_tf=_VAR_BLOCK_DEFAULT_EMPTY,
        tfvars={"stage.tfvars": 'github_org = "ExampleOrg"\n'},
    )
    result = validate_terraform_github_org(tf_dir)
    assert result.ok, result.errors


def test_terraform_github_org_fails_when_variable_has_no_default_and_no_override(
    tmp_path: Path,
) -> None:
    """`variable "github_org"` declared without a default and tfvars doesn't
    override — terraform would prompt at apply, but our static check should
    fail closed pre-deploy.
    """
    tf_dir = _write_tf_dir(
        tmp_path,
        variables_tf=_VAR_BLOCK_NO_DEFAULT,
        tfvars={"prod.tfvars": 'project_id = "example-security-project"\n'},
    )
    result = validate_terraform_github_org(tf_dir)
    assert not result.ok
    assert "prod.tfvars" in result.errors[0]


def test_terraform_github_org_skips_when_variables_tf_missing(tmp_path: Path) -> None:
    """Not a Terraform-managed tree (e.g. `make validate-config` invoked from
    a fork or outside the deploy layout) — skip silently rather than
    erroring on a missing file.
    """
    tf_dir = tmp_path / "no-such-tf-tree"
    result = validate_terraform_github_org(tf_dir)
    assert result.ok


def test_wiz_live_check_warns_when_registry_slug_missing(monkeypatch) -> None:
    monkeypatch.setenv("WIZ_API_URL", "https://api.example.wiz.io/graphql")
    monkeypatch.setenv("WIZ_CLIENT_ID", "id")
    monkeypatch.setenv("WIZ_CLIENT_SECRET", "secret")

    def fake_live() -> set[str]:
        return {"order-engine", "other-svc"}

    monkeypatch.setattr(
        "app.core.config_validate.fetch_wiz_application_service_names_from_env",
        fake_live,
    )
    registry = [
        {"key": "a", "wiz_service": "order-engine", "teams": ["order"]},
        {"key": "b", "wiz_service": "ghost-svc", "teams": ["order"]},
    ]
    result = validate_wiz_service_catalog_live(registry)
    assert result.ok
    assert any("ghost-svc" in w for w in result.warnings)
    assert any("other-svc" in w for w in result.warnings)


def test_wiz_live_check_skipped_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("WIZ_CLIENT_ID", raising=False)
    monkeypatch.delenv("WIZ_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("WIZ_API_URL", raising=False)
    result = validate_wiz_service_catalog_live(
        [{"key": "a", "wiz_service": "x", "teams": ["order"]}],
    )
    assert result.ok
    assert any("skipped live check" in w for w in result.warnings)


def test_terraform_github_org_no_tfvars_uses_default_only(tmp_path: Path) -> None:
    """Single-deploy mode (no env-specific tfvars files) — the default is
    the only effective value.
    """
    tf_dir = _write_tf_dir(
        tmp_path, variables_tf=_VAR_BLOCK_DEFAULT_ExampleOrgINC, tfvars={}
    )
    assert validate_terraform_github_org(tf_dir).ok

    tf_dir_empty = _write_tf_dir(
        tmp_path / "empty", variables_tf=_VAR_BLOCK_DEFAULT_EMPTY, tfvars={}
    )
    result = validate_terraform_github_org(tf_dir_empty)
    assert not result.ok
    assert "no tfvars override exists" in result.errors[0]
