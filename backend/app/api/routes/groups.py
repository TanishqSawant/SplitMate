"""Expense group and group member endpoints with authentication and IDOR protection."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import ExpenseGroup, GroupMember, User
from app.schemas.schemas import (
    GroupCreate,
    GroupResponse,
    GroupUpdate,
    MemberCreate,
    MemberResponse,
)
from app.services.authorization import require_group_membership

router = APIRouter(prefix="/api/groups", tags=["Groups"])


@router.post(
    "",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new expense group",
)
def create_group(
    body: GroupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = ExpenseGroup(name=body.name, creator_id=current_user.id)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.get(
    "",
    response_model=list[GroupResponse],
    summary="List all groups the current user belongs to",
)
def list_groups(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Groups created by user OR where user is a member
    normalized_email = current_user.email.strip().lower()
    groups = (
        db.query(ExpenseGroup)
        .outerjoin(GroupMember, ExpenseGroup.id == GroupMember.group_id)
        .filter(
            (ExpenseGroup.creator_id == current_user.id)
            | (GroupMember.user_id == current_user.id)
            | (func.lower(GroupMember.email) == normalized_email)
        )
        .distinct()
        .order_by(ExpenseGroup.created_at.desc())
        .all()
    )
    return groups


@router.get(
    "/{group_id}",
    response_model=GroupResponse,
    summary="Get a group by ID (requires membership)",
)
def get_group(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = require_group_membership(db, group_id, current_user)
    return group


@router.post(
    "/{group_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member to a group (requires membership)",
)
def add_member(
    group_id: uuid.UUID,
    body: MemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = require_group_membership(db, group_id, current_user)

    # Check if a registered user exists with this email to link user_id
    normalized_email = body.email.strip().lower()
    linked_user = (
        db.query(User)
        .filter(func.lower(User.email) == normalized_email)
        .first()
    )
    user_id = linked_user.id if linked_user else None

    member = GroupMember(
        group_id=group.id,
        user_id=user_id,
        name=body.name.strip(),
        email=normalized_email,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@router.get(
    "/{group_id}/members",
    response_model=list[MemberResponse],
    summary="List all members of a group (requires membership)",
)
def list_members(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = require_group_membership(db, group_id, current_user)
    return group.members


@router.put(
    "/{group_id}",
    response_model=GroupResponse,
    summary="Update an expense group",
)
def update_group(
    group_id: uuid.UUID,
    body: GroupUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = require_group_membership(db, group_id, current_user)
    group.name = body.name.strip()
    db.commit()
    db.refresh(group)
    return group


@router.delete(
    "/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an expense group",
)
def delete_group(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = require_group_membership(db, group_id, current_user)
    db.delete(group)
    db.commit()
    return None


@router.delete(
    "/{group_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from a group",
)
def remove_member(
    group_id: uuid.UUID,
    member_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = require_group_membership(db, group_id, current_user)
    member = db.get(GroupMember, member_id)
    if not member or member.group_id != group_id:
        raise HTTPException(status_code=404, detail="Member not found in this group.")
    db.delete(member)
    db.commit()
    return None
