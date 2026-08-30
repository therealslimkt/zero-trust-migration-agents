"""Atlas eligibility and closed dispatch-plan construction."""

from __future__ import annotations

import dataclasses

from .models import (
    CollaborationViolation,
    Portfolio,
    SpecialistCapability,
    SpecialistRequest,
    require_unique,
)
from .profiles import (
    ADVISOR_IDS,
    ANALYST_BY_FAMILY,
    PROFILE_BY_ID,
    SpecialistProfile,
    require_known_advisors,
)


_ADVISOR_CAPABILITY = {
    "scout": SpecialistCapability.INVENTORY_SOURCE,
    "maven": SpecialistCapability.RECOMMEND_DRIVER,
    "prisma": SpecialistCapability.PROPOSE_MAPPING,
    "jetty_advisor": SpecialistCapability.EXPLAIN_FAILURE,
}


@dataclasses.dataclass(frozen=True)
class EligibleTeam:
    portfolio: Portfolio
    profiles: tuple[SpecialistProfile, ...]
    required_analyst_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.portfolio, Portfolio):
            raise CollaborationViolation("eligible_portfolio")
        if type(self.profiles) is not tuple or not all(
            isinstance(profile, SpecialistProfile) for profile in self.profiles
        ):
            raise CollaborationViolation("eligible_profiles")
        if type(self.required_analyst_ids) is not frozenset:
            raise CollaborationViolation("eligible_required_analysts")

    @property
    def specialist_ids(self) -> frozenset[str]:
        return frozenset(profile.specialist_id for profile in self.profiles)


@dataclasses.dataclass(frozen=True)
class AtlasDispatchPlan:
    team: EligibleTeam
    selected_specialist_ids: tuple[str, ...]
    requests: tuple[SpecialistRequest, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.team, EligibleTeam):
            raise CollaborationViolation("dispatch_team")
        if type(self.selected_specialist_ids) is not tuple:
            raise CollaborationViolation("selected_specialists")
        if type(self.requests) is not tuple or not self.requests:
            raise CollaborationViolation("dispatch_requests")
        require_unique(self.selected_specialist_ids, "duplicate_selected_specialist")
        require_unique(
            tuple(request.request_id for request in self.requests),
            "duplicate_dispatch_request",
        )


def build_eligible_team(
    portfolio: Portfolio, *, permitted_advisor_ids: frozenset[str] = frozenset()
) -> EligibleTeam:
    """Include exactly the portfolio analysts plus explicitly permitted advisors."""

    if not isinstance(portfolio, Portfolio):
        raise CollaborationViolation("eligible_portfolio")
    if not isinstance(permitted_advisor_ids, frozenset):
        raise CollaborationViolation("permitted_advisors")
    require_known_advisors(permitted_advisor_ids)
    analyst_ids = frozenset(
        ANALYST_BY_FAMILY[source.family] for source in portfolio.sources
    )
    ordered_ids = tuple(
        profile_id
        for profile_id in PROFILE_BY_ID
        if profile_id in analyst_ids or profile_id in permitted_advisor_ids
    )
    return EligibleTeam(
        portfolio=portfolio,
        profiles=tuple(PROFILE_BY_ID[profile_id] for profile_id in ordered_ids),
        required_analyst_ids=analyst_ids,
    )


def plan_dispatch(
    team: EligibleTeam, *, selected_specialist_ids: tuple[str, ...]
) -> AtlasDispatchPlan:
    """Validate an Atlas selection and create one closed request per dispatch."""

    if not isinstance(team, EligibleTeam):
        raise CollaborationViolation("dispatch_team")
    if not selected_specialist_ids:
        raise CollaborationViolation("selected_specialists")
    require_unique(selected_specialist_ids, "duplicate_selected_specialist")
    selected = frozenset(selected_specialist_ids)
    if selected - team.specialist_ids:
        raise CollaborationViolation("unauthorized_specialist_selection")
    if not team.required_analyst_ids.issubset(selected):
        raise CollaborationViolation("missing_source_analyst")

    requests: list[SpecialistRequest] = []
    index = 0
    for specialist_id in selected_specialist_ids:
        profile = PROFILE_BY_ID[specialist_id]
        if profile.source_family is not None:
            source_groups = (
                (source.source_instance_id,)
                for source in team.portfolio.sources
                if source.family is profile.source_family
            )
            capability = SpecialistCapability.PROFILE_SCHEMA
        else:
            source_groups = (
                tuple(source.source_instance_id for source in team.portfolio.sources),
            )
            capability = _ADVISOR_CAPABILITY[specialist_id]
        for source_ids in source_groups:
            index += 1
            requests.append(
                SpecialistRequest(
                    request_id=f"req_{index:03d}_{specialist_id}",
                    run_id=team.portfolio.run_id,
                    session_id=team.portfolio.session_id,
                    specialist_id=specialist_id,
                    capability=capability,
                    source_instance_ids=source_ids,
                    objective=team.portfolio.objective,
                )
            )
    return AtlasDispatchPlan(
        team=team,
        selected_specialist_ids=selected_specialist_ids,
        requests=tuple(requests),
    )
