from datetime import date, datetime, timedelta
from app.core.utc import UTC
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, require_permission, require_staff
from app.core.time_utils import format_duration, format_hours_decimal
from app.db.session import get_db
from app.models.hr import AttendanceLog, CompanyHoliday, EmployeeProfile, LeaveRequest
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.hr import (
    LEAVE_TYPES,
    AttendanceOut,
    EmployeeOut,
    EmployeeProfileUpdate,
    HolidayCreate,
    HolidayOut,
    LeaveCreate,
    LeaveOut,
    LeaveReview,
)

router = APIRouter(prefix="/hr", tags=["hr"])

LEAVE_LABELS = {
    "annual": "Annual Leave",
    "casual": "Casual Leave",
    "medical": "Medical Leave",
}


def _user_name(user: User) -> str:
    return f"{user.first_name} {user.last_name or ''}".strip()


async def _get_or_create_profile(db: AsyncSession, company_id: UUID, user_id: UUID) -> EmployeeProfile:
    result = await db.execute(
        select(EmployeeProfile).where(
            EmployeeProfile.user_id == user_id,
            EmployeeProfile.company_id == company_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile:
        return profile
    profile = EmployeeProfile(company_id=company_id, user_id=user_id)
    db.add(profile)
    await db.flush()
    return profile


@router.get("/employees", response_model=list[EmployeeOut])
async def list_employees(
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.role))
        .where(User.company_id == current.company_id, User.is_active.is_(True))
        .order_by(User.first_name.asc())
    )
    users = [u for u in result.scalars().all() if u.role and u.role.name != "client"]
    today = date.today()
    month_start = today.replace(day=1)
    out: list[EmployeeOut] = []
    for user in users:
        if current.role_name == "employee" and user.id != current.id:
            continue
        profile = await _get_or_create_profile(db, current.company_id, user.id)
        att = await db.execute(
            select(AttendanceLog).where(
                AttendanceLog.user_id == user.id,
                AttendanceLog.work_date == today,
            )
        )
        today_log = att.scalar_one_or_none()
        work_sum = await db.execute(
            select(func.coalesce(func.sum(AttendanceLog.work_seconds), 0)).where(
                AttendanceLog.user_id == user.id,
                AttendanceLog.work_date >= month_start,
                AttendanceLog.work_date <= today,
            )
        )
        pending = await db.execute(
            select(func.count()).select_from(LeaveRequest).where(
                LeaveRequest.user_id == user.id,
                LeaveRequest.status == "pending",
            )
        )
        can_see_salary = current.can("manage_hr") or user.id == current.id
        out.append(
            EmployeeOut(
                user_id=user.id,
                name=_user_name(user),
                email=user.email,
                phone=user.phone,
                role=user.role.name if user.role else "employee",
                is_active=user.is_active,
                department=profile.department,
                designation=profile.designation,
                joining_date=profile.joining_date,
                salary=float(profile.salary or 0) if can_see_salary else 0,
                annual_leave_balance=profile.annual_leave_balance,
                casual_leave_balance=profile.casual_leave_balance,
                medical_leave_balance=profile.medical_leave_balance,
                notes=profile.notes if can_see_salary else None,
                today_status=today_log.status if today_log else "absent",
                month_work_hours=format_hours_decimal(int(work_sum.scalar_one())),
                pending_leaves=pending.scalar_one(),
            )
        )
    return out


@router.get("/employees/{user_id}", response_model=EmployeeOut)
async def get_employee(
    user_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    if current.role_name == "employee" and user_id != current.id:
        raise HTTPException(status_code=403, detail="Not allowed")
    employees = await list_employees(current=current, db=db)
    for emp in employees:
        if emp.user_id == user_id:
            return emp
    raise HTTPException(status_code=404, detail="Employee not found")


@router.patch("/employees/{user_id}", response_model=EmployeeOut)
async def update_employee_profile(
    user_id: UUID,
    body: EmployeeProfileUpdate,
    current: CurrentUser = Depends(require_permission("manage_hr")),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user or user.company_id != current.company_id:
        raise HTTPException(status_code=404, detail="Employee not found")
    profile = await _get_or_create_profile(db, current.company_id, user_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(profile, k, v)
    await db.flush()
    return await get_employee(user_id=user_id, current=current, db=db)


@router.post("/attendance/check-in", response_model=AttendanceOut)
async def check_in(
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    result = await db.execute(
        select(AttendanceLog).where(
            AttendanceLog.user_id == current.id,
            AttendanceLog.work_date == today,
        )
    )
    log = result.scalar_one_or_none()
    if log and log.check_in_at:
        raise HTTPException(status_code=400, detail="Already checked in today")
    now = datetime.now(UTC)
    if not log:
        log = AttendanceLog(
            company_id=current.company_id,
            user_id=current.id,
            work_date=today,
            check_in_at=now,
            status="present",
        )
        db.add(log)
    else:
        log.check_in_at = now
        log.status = "present"
    await db.flush()
    return await _attendance_out(db, log)


@router.post("/attendance/check-out", response_model=AttendanceOut)
async def check_out(
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    result = await db.execute(
        select(AttendanceLog).where(
            AttendanceLog.user_id == current.id,
            AttendanceLog.work_date == today,
        )
    )
    log = result.scalar_one_or_none()
    if not log or not log.check_in_at:
        raise HTTPException(status_code=400, detail="Check in first")
    if log.check_out_at:
        raise HTTPException(status_code=400, detail="Already checked out today")
    now = datetime.now(UTC)
    log.check_out_at = now
    log.work_seconds = max(0, int((now - log.check_in_at).total_seconds()))
    await db.flush()
    return await _attendance_out(db, log)


@router.get("/attendance", response_model=list[AttendanceOut])
async def list_attendance(
    user_id: UUID | None = None,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    start = from_date or (today - timedelta(days=30))
    end = to_date or today
    q = select(AttendanceLog).where(
        AttendanceLog.company_id == current.company_id,
        AttendanceLog.work_date >= start,
        AttendanceLog.work_date <= end,
    )
    if current.role_name == "employee" and not current.can("manage_hr"):
        q = q.where(AttendanceLog.user_id == current.id)
    elif user_id:
        q = q.where(AttendanceLog.user_id == user_id)
    q = q.order_by(AttendanceLog.work_date.desc())
    result = await db.execute(q)
    return [await _attendance_out(db, log) for log in result.scalars().all()]


@router.get("/attendance/today", response_model=AttendanceOut | None)
async def today_attendance(
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AttendanceLog).where(
            AttendanceLog.user_id == current.id,
            AttendanceLog.work_date == date.today(),
        )
    )
    log = result.scalar_one_or_none()
    if not log:
        return None
    return await _attendance_out(db, log)


@router.get("/leaves", response_model=list[LeaveOut])
async def list_leaves(
    status_filter: str | None = None,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    q = select(LeaveRequest).where(LeaveRequest.company_id == current.company_id)
    if current.role_name == "employee" and not current.can("manage_hr"):
        q = q.where(LeaveRequest.user_id == current.id)
    if status_filter:
        q = q.where(LeaveRequest.status == status_filter)
    q = q.order_by(LeaveRequest.created_at.desc())
    result = await db.execute(q)
    return [await _leave_out(db, leave) for leave in result.scalars().all()]


@router.post("/leaves", response_model=LeaveOut, status_code=status.HTTP_201_CREATED)
async def create_leave(
    body: LeaveCreate,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    if body.leave_type not in LEAVE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid leave type")
    if body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date")
    days = (body.end_date - body.start_date).days + 1
    leave = LeaveRequest(
        company_id=current.company_id,
        user_id=current.id,
        leave_type=body.leave_type,
        start_date=body.start_date,
        end_date=body.end_date,
        days=days,
        reason=body.reason,
        status="pending",
    )
    db.add(leave)
    await db.flush()
    return await _leave_out(db, leave)


@router.patch("/leaves/{leave_id}", response_model=LeaveOut)
async def review_leave(
    leave_id: UUID,
    body: LeaveReview,
    current: CurrentUser = Depends(require_permission("manage_hr")),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Status must be approved or rejected")
    result = await db.execute(
        select(LeaveRequest).where(
            LeaveRequest.id == leave_id,
            LeaveRequest.company_id == current.company_id,
        )
    )
    leave = result.scalar_one_or_none()
    if not leave:
        raise HTTPException(status_code=404, detail="Leave request not found")
    if leave.status != "pending":
        raise HTTPException(status_code=400, detail="Leave already reviewed")

    leave.status = body.status
    leave.reviewed_by_id = current.id
    leave.reviewed_at = datetime.now(UTC)
    leave.review_note = body.review_note

    if body.status == "approved":
        profile = await _get_or_create_profile(db, current.company_id, leave.user_id)
        balance_field = {
            "annual": "annual_leave_balance",
            "casual": "casual_leave_balance",
            "medical": "medical_leave_balance",
        }.get(leave.leave_type)
        if balance_field:
            current_balance = getattr(profile, balance_field)
            setattr(profile, balance_field, max(0, current_balance - leave.days))

    await db.flush()
    return await _leave_out(db, leave)


@router.get("/holidays", response_model=list[HolidayOut])
async def list_holidays(
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CompanyHoliday)
        .where(CompanyHoliday.company_id == current.company_id)
        .order_by(CompanyHoliday.holiday_date.asc())
    )
    return list(result.scalars().all())


@router.post("/holidays", response_model=HolidayOut, status_code=status.HTTP_201_CREATED)
async def create_holiday(
    body: HolidayCreate,
    current: CurrentUser = Depends(require_permission("manage_hr")),
    db: AsyncSession = Depends(get_db),
):
    holiday = CompanyHoliday(
        company_id=current.company_id,
        title=body.title,
        holiday_date=body.holiday_date,
        is_optional=body.is_optional,
    )
    db.add(holiday)
    await db.flush()
    return holiday


@router.delete("/holidays/{holiday_id}", response_model=MessageResponse)
async def delete_holiday(
    holiday_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_hr")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CompanyHoliday).where(
            CompanyHoliday.id == holiday_id,
            CompanyHoliday.company_id == current.company_id,
        )
    )
    holiday = result.scalar_one_or_none()
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found")
    await db.delete(holiday)
    return MessageResponse(message="Holiday deleted")


async def _attendance_out(db: AsyncSession, log: AttendanceLog) -> AttendanceOut:
    user = await db.get(User, log.user_id)
    return AttendanceOut(
        id=log.id,
        user_id=log.user_id,
        user_name=_user_name(user) if user else None,
        work_date=log.work_date,
        check_in_at=log.check_in_at,
        check_out_at=log.check_out_at,
        status=log.status,
        work_seconds=log.work_seconds,
        work_label=format_duration(log.work_seconds),
        notes=log.notes,
    )


async def _leave_out(db: AsyncSession, leave: LeaveRequest) -> LeaveOut:
    user = await db.get(User, leave.user_id)
    reviewer = await db.get(User, leave.reviewed_by_id) if leave.reviewed_by_id else None
    return LeaveOut(
        id=leave.id,
        user_id=leave.user_id,
        user_name=_user_name(user) if user else None,
        leave_type=leave.leave_type,
        leave_type_label=LEAVE_LABELS.get(leave.leave_type, leave.leave_type),
        start_date=leave.start_date,
        end_date=leave.end_date,
        days=leave.days,
        reason=leave.reason,
        status=leave.status,
        reviewed_by_id=leave.reviewed_by_id,
        reviewed_by_name=_user_name(reviewer) if reviewer else None,
        reviewed_at=leave.reviewed_at,
        review_note=leave.review_note,
        created_at=leave.created_at,
    )
