"""Who is in AIM, and as what."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...deps import get_db
from ...models import User
from . import strings
from .deps import AimIdentity, count_explicit_teachers, get_identity, require_teacher
from .models import ROLE_TEACHER, AimMember
from .schemas import AimCandidateRead, AimIdentityRead, AimMemberRead, AimMemberUpdate

router = APIRouter()


@router.get("/me", response_model=AimIdentityRead)
def read_identity(identity: AimIdentity = Depends(get_identity)):
    """The caller's standing in AIM.

    Answers for any signed-in user, including one with no role — the client asks
    this before it decides whether to show the module at all, so "no" has to be
    an answer rather than a 403.
    """
    return AimIdentityRead(
        user_id=identity.user.id,
        role=identity.role,
        is_hub_admin=identity.user.is_admin,
        implicit=identity.implicit,
    )


@router.get("/members", response_model=list[AimMemberRead])
def list_members(
    session: Session = Depends(get_db),
    _: AimIdentity = Depends(require_teacher),
):
    """Everyone with an AIM role, granted or inferred.

    Hub admins appear with ``implicit`` set even without a row, because a roster
    that hides them would look wrong to the admin reading it.
    """
    granted = {member.user_id: member.role for member in session.query(AimMember).all()}
    users = (
        session.query(User).filter(User.is_active.is_(True)).order_by(User.created_at.asc()).all()
    )

    roster: list[AimMemberRead] = []
    for user in users:
        # The same precedence `resolve_identity` applies, inlined so the roster
        # is two queries rather than one per user.
        role = granted.get(user.id) or (ROLE_TEACHER if user.is_admin else None)
        if role is None:
            continue
        roster.append(
            AimMemberRead(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                role=role,
                implicit=user.id not in granted,
            )
        )
    return roster


@router.get("/roster/candidates", response_model=list[AimCandidateRead])
def list_candidates(
    session: Session = Depends(get_db),
    _: AimIdentity = Depends(require_teacher),
):
    """Active hub users with no AIM row.

    This exists because ``GET /users`` is admin-only and an AIM teacher may not
    be a hub admin. It answers only the question the roster screen asks.
    """
    taken = {user_id for (user_id,) in session.query(AimMember.user_id).all()}
    users = (
        session.query(User)
        .filter(User.is_active.is_(True))
        .order_by(User.created_at.asc())
        .all()
    )
    return [AimCandidateRead.model_validate(user) for user in users if user.id not in taken]


@router.put("/members/{user_id}", response_model=AimMemberRead)
def set_member_role(
    user_id: int,
    payload: AimMemberUpdate,
    session: Session = Depends(get_db),
    _: AimIdentity = Depends(require_teacher),
):
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=strings.USER_NOT_FOUND)

    member = session.query(AimMember).filter(AimMember.user_id == user_id).first()
    _guard_last_teacher(session, member, becoming=payload.role)

    if member is None:
        member = AimMember(user_id=user_id, role=payload.role)
        session.add(member)
    else:
        member.role = payload.role
    session.commit()

    return AimMemberRead(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=payload.role,
        implicit=False,
    )


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: int,
    session: Session = Depends(get_db),
    _: AimIdentity = Depends(require_teacher),
):
    member = session.query(AimMember).filter(AimMember.user_id == user_id).first()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=strings.MEMBER_NOT_FOUND)
    _guard_last_teacher(session, member, becoming=None)

    session.delete(member)
    session.commit()


def _guard_last_teacher(session: Session, member: AimMember | None, *, becoming: str | None) -> None:
    """Refuse a change that would leave AIM with no granted teacher.

    Mirrors the last-administrator guard in ``api/users.py``: without it, one
    demotion leaves a library nobody can run a session from, and no way to undo
    it through the API.
    """
    if member is None or member.role != ROLE_TEACHER or becoming == ROLE_TEACHER:
        return
    if count_explicit_teachers(session, excluding=member.user_id) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=strings.LAST_TEACHER)
