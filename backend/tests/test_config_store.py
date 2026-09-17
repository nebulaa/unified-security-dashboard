"""Unit tests for `OwnershipMap.team_for_asset` (config_store.py).

The interesting behaviour pinned here is the case-insensitive fallback for
the `repo:` namespace and the case-sensitive contract for `sonarproj:` —
both load-bearing for the `example-service` see-saw fix (asset_ids written under
a transient empty `GITHUB_ORG` arrived lowercase; the fallback recovers
their owner team, while `sonarproj:` lookups stay strict because Sonar
project keys are case-sensitive identifiers in the upstream system).
"""

from __future__ import annotations

from app.core.config_store import OwnershipMap, TeamConfig


def _om(asset_to_team: dict[str, str], **kwargs) -> OwnershipMap:
    return OwnershipMap(
        asset_to_team=asset_to_team,
        teams={"tsea": TeamConfig(name="tsea"), "pin": TeamConfig(name="pin")},
        **kwargs,
    )


def test_team_for_asset_exact_match_repo() -> None:
    om = _om({"repo:ExampleOrg/example-service": "tsea"})
    assert om.team_for_asset("repo:ExampleOrg/example-service") == "tsea"


def test_team_for_asset_case_insensitive_repo_lookup() -> None:
    """A stored lowercase `asset_id` (e.g. legacy `repo:exampleorg/example-service`)
    still resolves to the team listed under the canonical mixed-case key in
    `ownership.yaml`. This is the runtime safety net that closes the
    see-saw between ingest re-stamp and rollup `core_reresolve`.
    """
    om = _om({"repo:ExampleOrg/example-service": "tsea"})
    assert om.team_for_asset("repo:exampleorg/example-service") == "tsea"
    assert om.team_for_asset("repo:EXAMPLEORG/example-service") == "tsea"
    assert om.team_for_asset("repo:ExampleOrg/EXAMPLE-SERVICE") == "tsea"


def test_team_for_asset_repo_unmapped_falls_through_to_unowned() -> None:
    om = _om({"repo:ExampleOrg/example-service": "tsea"})
    assert om.team_for_asset("repo:ExampleOrg/something-else") == "unowned"
    assert om.team_for_asset("repo:exampleorg/something-else") == "unowned"


def test_team_for_asset_exact_match_takes_precedence_over_case_fold() -> None:
    """If both `repo:Foo/bar` and `repo:foo/bar` are listed (deliberately or
    accidentally), the exact-cased lookup wins so callers passing the
    canonical id always see the canonical team — only callers passing a
    drifted-case id fall through to the lowercase index.
    """
    om = _om(
        {
            "repo:ExampleOrg/example": "tsea",
            "repo:exampleorg/example": "pin",
        }
    )
    assert om.team_for_asset("repo:ExampleOrg/example") == "tsea"
    assert om.team_for_asset("repo:exampleorg/example") == "pin"


def test_team_for_asset_sonarproj_remains_case_sensitive() -> None:
    """Sonar project keys are case-sensitive in the upstream system — the
    case-folding fallback applies to `repo:` only. Lower-casing
    `sonarproj:Foo` to `sonarproj:foo` would silently match a different
    Sonar project and stamp the wrong team.
    """
    om = _om({"sonarproj:ExampleOrg.Commerce.Orders.API": "tsea"})
    assert om.team_for_asset("sonarproj:ExampleOrg.Commerce.Orders.API") == "tsea"
    assert om.team_for_asset("sonarproj:exampleorg.commerce.orders.api") == "unowned"
    assert om.team_for_asset("sonarproj:ExampleOrg.Commerce.ORDERS.API") == "unowned"


def test_team_for_asset_excluded_repo_short_circuits_to_excluded() -> None:
    """`excluded_repos` short-circuits to `excluded` regardless of asset_id
    casing — the repo short-name is what's listed in YAML.
    """
    om = _om(
        {"repo:ExampleOrg/product-sandbox": "pin"},
        excluded_repos=frozenset({"product-sandbox"}),
    )
    assert om.team_for_asset("repo:ExampleOrg/product-sandbox") == "excluded"
    assert om.team_for_asset("repo:exampleorg/product-sandbox") == "excluded"


def test_team_for_asset_non_repo_namespace_is_strict() -> None:
    """The lowercase-fallback is scoped to `repo:` — anything else (today
    just `sonarproj:`, but future namespaces too) goes through the strict
    dict lookup so we don't accidentally case-fold an upstream identifier
    that's case-significant.
    """
    om = _om({"weird:ExampleOrg/x": "tsea"})
    assert om.team_for_asset("weird:ExampleOrg/x") == "tsea"
    assert om.team_for_asset("weird:exampleorg/x") == "unowned"


def test_team_for_asset_repo_without_slash_skips_repo_branch() -> None:
    """Defensive: an `asset_id` shaped like `repo:foo` (no `/`) doesn't enter
    the repo branch at all — falls back to the strict dict lookup, mirroring
    the existing pre-fallback behaviour.
    """
    om = _om({"repo:lone-repo-name": "tsea"})
    assert om.team_for_asset("repo:lone-repo-name") == "tsea"
    assert om.team_for_asset("repo:LONE-REPO-NAME") == "unowned"
