"""Expense group and group member endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import ExpenseGroup, GroupMember
from app.schemas.schemas import (
    GroupCreate,
    GroupResponse,
    MemberCreate,
    MemberResponse,
)

router = APIRouter(prefix="/api/groups", tags=["Groups"])


@router.post(
    "",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new expense group",
)
def create_group(body: GroupCreate, db: Session = Depends(get_db)):
    group = ExpenseGroup(name=body.name)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.get(
    "/{group_id}",
    response_model=GroupResponse,
    summary="Get a group by ID",
)
def get_group(group_id: uuid.UUID, db: Session = Depends(get_db)):
    group = db.get(ExpenseGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found.")
    return group


@router.post(
    "/{group_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member to a group",
)
def add_member(
    group_id: uuid.UUID, body: MemberCreate, db: Session = Depends(get_db)
):
    group = db.get(ExpenseGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found.")

    member = GroupMember(group_id=group_id, name=body.name, email=body.email)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@router.get(
    "/{group_id}/members",
    response_model=list[MemberResponse],
    summary="List all members of a group",
)
def list_members(group_id: uuid.UUID, db: Session = Depends(get_db)):
    group = db.get(ExpenseGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found.")
    return group.members

