"""Access and organisation bootstrap helpers."""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model

from accounts.models import DoctorProfile

from emr.models import Organisation, OrganisationMembership


@dataclass(frozen=True)
class EMRContext:
    organisation: Organisation
    membership: OrganisationMembership


def _role_for_user(user) -> str:
    if user.is_superuser or user.is_staff:
        return "system_admin"
    profile = DoctorProfile.objects.filter(user=user).first()
    if not profile:
        return "doctor"
    if profile.role == DoctorProfile.ROLE_ADMIN:
        return "system_admin"
    return "doctor"


def _default_org_name(user) -> str:
    profile = DoctorProfile.objects.filter(user=user).first()
    if profile and profile.facility:
        return profile.facility
    if user.get_full_name():
        return f"{user.get_full_name()}'s Clinic"
    return f"{user.username}'s Clinic"


def ensure_default_membership(user) -> EMRContext:
    membership = (
        OrganisationMembership.objects.select_related("organisation")
        .filter(user=user, is_default=True)
        .first()
    )
    if membership:
        return EMRContext(organisation=membership.organisation, membership=membership)

    existing_membership = (
        OrganisationMembership.objects.select_related("organisation")
        .filter(user=user)
        .first()
    )
    if existing_membership:
        existing_membership.is_default = True
        existing_membership.save(update_fields=["is_default", "updated_at"])
        return EMRContext(
            organisation=existing_membership.organisation,
            membership=existing_membership,
        )

    organisation = Organisation.objects.create(
        name=_default_org_name(user),
        organisation_type="private_clinic",
    )
    membership = OrganisationMembership.objects.create(
        organisation=organisation,
        user=user,
        role=_role_for_user(user),
        is_default=True,
    )
    return EMRContext(organisation=organisation, membership=membership)


def get_membership(user, organisation_id=None) -> EMRContext:
    if organisation_id is None:
        return ensure_default_membership(user)

    membership = (
        OrganisationMembership.objects.select_related("organisation")
        .filter(user=user, organisation_id=organisation_id)
        .first()
    )
    if membership is None:
        return ensure_default_membership(user)
    return EMRContext(organisation=membership.organisation, membership=membership)


def membership_for_request(request, organisation_id=None) -> EMRContext:
    return get_membership(request.user, organisation_id=organisation_id)


def user_choices_for_organisation(organisation):
    User = get_user_model()
    return User.objects.filter(
        organisation_memberships__organisation=organisation
    ).distinct()
