from __future__ import annotations

import re
from datetime import date

from ..models import Employment, ParticipantProfile


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def set_current_company(profile: ParticipantProfile, company_id: str) -> None:
    current = profile.current_employment
    if current and current.company_id == company_id:
        return
    if current:
        current.is_current = False
        current.ended_on = date.today()
    if company_id:
        profile.employments.append(
            Employment(company_id=company_id, started_on=date.today(), is_current=True)
        )
