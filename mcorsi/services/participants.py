from __future__ import annotations

import re
from datetime import date, datetime, timezone

from ..models import Employment, ParticipantProfile, User


class EmploymentVerificationError(ValueError):
    pass


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def normalize_vat_number(value: str) -> str:
    normalized = normalize_identifier(value)
    if normalized.startswith("IT") and normalized[2:].isdigit():
        return normalized[2:]
    return normalized


def vat_number_variants(value: str) -> tuple[str, ...]:
    normalized = normalize_vat_number(value)
    if len(normalized) == 11 and normalized.isdigit():
        return normalized, f"IT{normalized}"
    return (normalized,)


def is_valid_italian_vat_number(value: str) -> bool:
    digits = normalize_vat_number(value)
    if len(digits) != 11 or not digits.isdigit():
        return False
    total = sum(int(digits[index]) for index in range(0, 10, 2))
    for index in range(1, 10, 2):
        doubled = int(digits[index]) * 2
        total += doubled - 9 if doubled > 9 else doubled
    return (10 - total % 10) % 10 == int(digits[-1])


def _close_current_employment(profile: ParticipantProfile) -> None:
    current = profile.current_employment
    if current:
        current.is_current = False
        current.ended_on = date.today()


def _withdraw_pending_employments(
    profile: ParticipantProfile, *, except_employment: Employment | None = None
) -> None:
    now = datetime.now(timezone.utc)
    for employment in profile.employments:
        if employment is except_employment or employment.verification_status != "pending":
            continue
        employment.verification_status = "rejected"
        employment.is_current = False
        employment.ended_on = employment.ended_on or date.today()
        employment.reviewed_at = now


def set_current_company(
    profile: ParticipantProfile, company_id: str, *, actor: User | None = None
) -> Employment | None:
    current = profile.current_employment
    if current and current.company_id == company_id:
        _withdraw_pending_employments(profile)
        return current
    if not company_id:
        _close_current_employment(profile)
        _withdraw_pending_employments(profile)
        return None

    candidate = next(
        (
            item
            for item in profile.employments
            if item.company_id == company_id
            and not item.is_current
            and item.started_on == date.today()
        ),
        None,
    )
    if candidate is None:
        candidate = Employment(company_id=company_id, started_on=date.today())
        profile.employments.append(candidate)
    _close_current_employment(profile)
    _withdraw_pending_employments(profile, except_employment=candidate)
    candidate.verification_status = "verified"
    candidate.is_current = True
    candidate.ended_on = None
    candidate.requested_by_user_id = candidate.requested_by_user_id or (actor.id if actor else None)
    candidate.reviewed_by_user_id = actor.id if actor else None
    candidate.reviewed_at = datetime.now(timezone.utc)
    return candidate


def request_company_association(
    profile: ParticipantProfile, company_id: str, *, requester: User
) -> Employment | None:
    current = profile.current_employment
    if not company_id:
        _close_current_employment(profile)
        _withdraw_pending_employments(profile)
        return None
    if current and current.company_id == company_id:
        _withdraw_pending_employments(profile)
        return current

    pending = profile.pending_employment
    if pending and pending.company_id == company_id:
        return pending
    _withdraw_pending_employments(profile)
    employment = next(
        (
            item
            for item in profile.employments
            if item.company_id == company_id
            and not item.is_current
            and item.started_on == date.today()
        ),
        None,
    )
    if employment is None:
        employment = Employment(company_id=company_id, started_on=date.today())
        profile.employments.append(employment)
    employment.is_current = False
    employment.ended_on = None
    employment.verification_status = "pending"
    employment.requested_by_user_id = requester.id
    employment.reviewed_by_user_id = None
    employment.reviewed_at = None
    return employment


def approve_company_association(employment: Employment, *, actor: User) -> None:
    if employment.verification_status != "pending":
        raise EmploymentVerificationError("La richiesta è già stata esaminata.")
    if employment.company.verification_status != "verified":
        raise EmploymentVerificationError(
            "Verifica prima l'azienda associata alla richiesta."
        )
    profile = employment.participant
    _close_current_employment(profile)
    _withdraw_pending_employments(profile, except_employment=employment)
    employment.verification_status = "verified"
    employment.is_current = True
    employment.ended_on = None
    employment.reviewed_by_user_id = actor.id
    employment.reviewed_at = datetime.now(timezone.utc)


def reject_company_association(employment: Employment, *, actor: User) -> None:
    if employment.verification_status != "pending":
        raise EmploymentVerificationError("La richiesta è già stata esaminata.")
    employment.verification_status = "rejected"
    employment.is_current = False
    employment.ended_on = employment.ended_on or date.today()
    employment.reviewed_by_user_id = actor.id
    employment.reviewed_at = datetime.now(timezone.utc)
