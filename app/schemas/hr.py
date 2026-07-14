from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

LEAVE_TYPES = {"annual", "casual", "medical"}
LEAVE_STATUSES = {"pending", "approved", "rejected"}


class EmployeeProfileUpdate(BaseModel):
    department: str | None = None
    designation: str | None = None
    joining_date: date | None = None
    salary: float | None = None
    annual_leave_balance: int | None = None
    casual_leave_balance: int | None = None
    medical_leave_balance: int | None = None
    notes: str | None = None


class EmployeeOut(BaseModel):
    user_id: UUID
    name: str
    email: str
    phone: str | None = None
    role: str
    is_active: bool
    department: str | None = None
    designation: str | None = None
    joining_date: date | None = None
    salary: float = 0
    annual_leave_balance: int = 12
    casual_leave_balance: int = 6
    medical_leave_balance: int = 6
    notes: str | None = None
    today_status: str | None = None
    month_work_hours: float = 0
    pending_leaves: int = 0


class AttendanceOut(ORMModel):
    id: UUID
    user_id: UUID
    user_name: str | None = None
    work_date: date
    check_in_at: datetime | None
    check_out_at: datetime | None
    status: str
    work_seconds: int
    work_label: str
    notes: str | None


class LeaveCreate(BaseModel):
    leave_type: str
    start_date: date
    end_date: date
    reason: str | None = None


class LeaveReview(BaseModel):
    status: str
    review_note: str | None = None


class LeaveOut(ORMModel):
    id: UUID
    user_id: UUID
    user_name: str | None = None
    leave_type: str
    leave_type_label: str
    start_date: date
    end_date: date
    days: int
    reason: str | None
    status: str
    reviewed_by_id: UUID | None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime


class HolidayCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    holiday_date: date
    is_optional: bool = False


class HolidayOut(ORMModel):
    id: UUID
    title: str
    holiday_date: date
    is_optional: bool
    created_at: datetime
