"""Canonical product-agent profiles and deterministic Atlas team selection."""

from __future__ import annotations

import dataclasses

from .models import AgentMode, SourceFamily, SpecialistCapability
from .models import CollaborationViolation


ATLAS_ID = "atlas"
SCOUT_ID = "scout"
MAVEN_ID = "maven"
PRISMA_ID = "prisma"
JETTY_ADVISOR_ID = "jetty_advisor"

ANALYST_BY_FAMILY = {
    SourceFamily.SAP: "source_analyst_sap",
    SourceFamily.JDE: "source_analyst_jde",
    SourceFamily.ORACLE: "source_analyst_oracle",
    SourceFamily.COBOL: "source_analyst_cobol",
    SourceFamily.IBMI: "source_analyst_ibmi",
    SourceFamily.SAGE: "source_analyst_sage",
    SourceFamily.AX: "source_analyst_ax",
}


@dataclasses.dataclass(frozen=True)
class SpecialistProfile:
    specialist_id: str
    mode: AgentMode
    description: str
    capabilities: frozenset[SpecialistCapability]
    source_family: SourceFamily | None = None


def _analyst_profile(family: SourceFamily, description: str) -> SpecialistProfile:
    return SpecialistProfile(
        specialist_id=ANALYST_BY_FAMILY[family],
        mode=AgentMode.SINGLE_TURN,
        description=description,
        capabilities=frozenset(
            {
                SpecialistCapability.INVENTORY_SOURCE,
                SpecialistCapability.PROFILE_SCHEMA,
            }
        ),
        source_family=family,
    )


ATLAS_PROFILE = SpecialistProfile(
    specialist_id=ATLAS_ID,
    mode=AgentMode.CHAT,
    description="Coordinates eligible specialists and alone speaks to the user.",
    capabilities=frozenset(),
)

SOURCE_ANALYST_PROFILES = (
    _analyst_profile(SourceFamily.SAP, "Interprets sanitized SAP ECC and MaxDB metadata."),
    _analyst_profile(
        SourceFamily.JDE,
        "Interprets sanitized JDE EnterpriseOne on IBM i metadata.",
    ),
    _analyst_profile(
        SourceFamily.ORACLE,
        "Interprets sanitized Oracle E-Business Suite metadata.",
    ),
    _analyst_profile(SourceFamily.COBOL, "Interprets the supported sanitized z/OS COBOL subset."),
    _analyst_profile(SourceFamily.IBMI, "Interprets sanitized native IBM i metadata."),
    _analyst_profile(SourceFamily.SAGE, "Interprets sanitized Sage CRE and Zen metadata."),
    _analyst_profile(SourceFamily.AX, "Interprets sanitized Dynamics AX metadata."),
)

ADVISOR_PROFILES = (
    SpecialistProfile(
        specialist_id=SCOUT_ID,
        mode=AgentMode.SINGLE_TURN,
        description="Interprets governed catalog search intent without bypassing queries.",
        capabilities=frozenset({SpecialistCapability.INVENTORY_SOURCE}),
    ),
    SpecialistProfile(
        specialist_id=MAVEN_ID,
        mode=AgentMode.SINGLE_TURN,
        description="Researches documented runtime, driver, format, and CDC gaps.",
        capabilities=frozenset({SpecialistCapability.RECOMMEND_DRIVER}),
    ),
    SpecialistProfile(
        specialist_id=PRISMA_ID,
        mode=AgentMode.SINGLE_TURN,
        description="Advises on closed declarative transform mappings.",
        capabilities=frozenset(
            {SpecialistCapability.PROPOSE_MAPPING, SpecialistCapability.VALIDATE_PLAN}
        ),
    ),
    SpecialistProfile(
        specialist_id=JETTY_ADVISOR_ID,
        mode=AgentMode.SINGLE_TURN,
        description="Explains privacy findings without making policy decisions.",
        capabilities=frozenset({SpecialistCapability.EXPLAIN_FAILURE}),
    ),
)

ALL_SPECIALIST_PROFILES = SOURCE_ANALYST_PROFILES + ADVISOR_PROFILES
PROFILE_BY_ID = {profile.specialist_id: profile for profile in ALL_SPECIALIST_PROFILES}
ADVISOR_IDS = frozenset(profile.specialist_id for profile in ADVISOR_PROFILES)


def require_known_advisors(permitted_advisor_ids: frozenset[str]) -> None:
    unknown = permitted_advisor_ids - ADVISOR_IDS
    if unknown:
        raise CollaborationViolation("unknown_advisor")
