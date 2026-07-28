"""Who may do what in AIM.

The hub has exactly one authorisation bit, ``is_admin``, and AIM needs a
different distinction that does not map onto it: an institute has many maths
teachers and one or two people who administer the server. So membership is
AIM's own table, and the hub's auth model is left alone.

Resolution order, which every route depends on:

1. an explicit :class:`AimMember` row wins;
2. otherwise a hub admin is treated as a teacher, so a fresh install is never
   locked out of the screen that grants the first real membership;
3. otherwise the user has no AIM role at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...deps import get_current_user, get_db
from ...models import User
from . import strings
from .models import ROLE_STUDENT, ROLE_TEACHER, AimMember


@dataclass(slots=True)
class AimIdentity:
    user: User
    role: str | None
    implicit: bool

    @property
    def is_teacher(self) -> bool:
        return self.role == ROLE_TEACHER

    @property
    def is_student(self) -> bool:
        return self.role == ROLE_STUDENT


def resolve_identity(session: Session, user: User) -> AimIdentity:
    member = session.query(AimMember).filter(AimMember.user_id == user.id).first()
    if member is not None:
        return AimIdentity(user=user, role=member.role, implicit=False)
    if user.is_admin:
        return AimIdentity(user=user, role=ROLE_TEACHER, implicit=True)
    return AimIdentity(user=user, role=None, implicit=False)


def get_identity(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AimIdentity:
    """The caller's AIM standing, whatever it is. Never raises."""
    return resolve_identity(session, user)


def require_member(identity: AimIdentity = Depends(get_identity)) -> AimIdentity:
    if identity.role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.NOT_A_MEMBER)
    return identity


def require_teacher(identity: AimIdentity = Depends(get_identity)) -> AimIdentity:
    # Someone with no AIM role at all is told that, rather than "teachers only":
    # the first is something they can act on, the second sounds like a mistake.
    if identity.role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.NOT_A_MEMBER)
    if not identity.is_teacher:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.TEACHER_ONLY)
    return identity


def require_student(identity: AimIdentity = Depends(get_identity)) -> AimIdentity:
    if identity.role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.NOT_A_MEMBER)
    if not identity.is_student:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=strings.STUDENT_ONLY)
    return identity


def count_explicit_teachers(session: Session, *, excluding: int | None = None) -> int:
    """Granted teachers only.

    Implicit hub-admin teachers are not counted, because they cannot be removed
    through this API — so a hub whose only teachers are admins is not at risk of
    the lockout the last-teacher guard exists to prevent.
    """
    query = session.query(AimMember).filter(AimMember.role == ROLE_TEACHER)
    if excluding is not None:
        query = query.filter(AimMember.user_id != excluding)
    return query.count()
