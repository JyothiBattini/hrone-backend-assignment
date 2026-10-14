"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

db.employees.create_index("emp_code", unique=True)
db.employees.create_index(
    [("department", 1), ("joined_on", 1)]
)
db.attendance_logs.create_index(
    [("emp_code", 1), ("date", 1)],
    unique=True
)
db.attendance_logs.create_index(
    [("date", -1), ("emp_code", 1)]
)


IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Helpers
def get_attendance_date(
    punch_in: datetime,
    shift_start: str,
    shift_end: str,
) -> str:
    punch_in_ist = punch_in.astimezone(IST)
    attendance_day = punch_in_ist.date()

    # Overnight shift: for example, 22:00 to 06:00.
    if shift_end <= shift_start:
        end_hour, end_minute = map(int, shift_end.split(":"))

        shift_end_time = datetime.min.time().replace(
            hour=end_hour,
            minute=end_minute,
        )

        if punch_in_ist.time() < shift_end_time:
            attendance_day -= timedelta(days=1)

    return attendance_day.isoformat()
def serialize_attendance(doc: dict) -> dict:
    result = {key: value for key, value in doc.items() if key != "_id"}

    for field in ("punch_in", "punch_out"):
        value = result.get(field)

        if isinstance(value, datetime):
            result[field] = int(
                value.replace(tzinfo=timezone.utc).timestamp() * 1000
            )

    result["history"] = result.get("history", [])
    result["half_day"] = result.get("half_day", False)

    return result

# --------------------------------------------------------------------------- #
def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    attendance_date: str,
) -> int:
    hour, minute = map(int, shift_start.split(":"))

    shift_start_dt = datetime.combine(
        date.fromisoformat(attendance_date),
        datetime.min.time(),
        tzinfo=IST,
    ).replace(hour=hour, minute=minute)

    punch_in_ist = punch_in.astimezone(IST)

    seconds_late = (punch_in_ist - shift_start_dt).total_seconds()

    if seconds_late <= 600:
        return 0

    return int(seconds_late // 60)


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = int((punch_out - punch_in).total_seconds())
    hours = Decimal(seconds) / Decimal(3600)
    return float(
        hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )

def compute_overtime(
    punch_out: datetime,
    shift_end: str,
    date_str: str,
    shift_start: str,
) -> int:
    hour, minute = map(int, shift_end.split(":"))

    shift_end_dt = datetime.combine(
        date.fromisoformat(date_str),
        datetime.min.time(),
        tzinfo=IST,
    ).replace(hour=hour, minute=minute)

    if shift_end <= shift_start:
        shift_end_dt += timedelta(days=1)

    punch_out_ist = punch_out.astimezone(IST)
    overtime_minutes = int(
        (punch_out_ist - shift_end_dt).total_seconds() // 60
    )

    return overtime_minutes if overtime_minutes >= 30 else 0

# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

class EmployeeIn(BaseModel):
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(
        max_length=120,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = Field(
        default="09:30",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    shift_end: str = Field(
        default="18:30",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    joined_on: date

    @model_validator(mode="after")
    def validate_shift_times(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_end must differ from shift_start")
        return self

class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = Field(
        default=None,
        strict=True,
        ge=100000000000,
        le=4102444800000,
    )
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"


class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = Field(
        default=None,
        strict=True,
        ge=100000000000,
        le=4102444800000,
    )
class RegularizeIn(BaseModel):
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)

    status: Optional[
        Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]
    ] = None

    punch_in: Optional[int] = Field(
        default=None,
        strict=True,
        ge=100000000000,
        le=4102444800000,
    )

    punch_out: Optional[int] = Field(
        default=None,
        strict=True,
        ge=100000000000,
        le=4102444800000,
    )
# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        ) 
    

@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump(mode="json")
    created_at = datetime.now(timezone.utc)
    doc["created_at"] = created_at

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="emp_code already exists"
        )

    return {
        **body.model_dump(mode="json"),
        "created_at": int(created_at.timestamp() * 1000)
    }





@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    q = {"department": department} if department else {}

    total = db.employees.count_documents(q)

    items = list(
        db.employees.find(q, {"_id": 0})
        .sort("emp_code", 1)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    for employee in items:
        employee["created_at"] = int(
            employee["created_at"].replace(tzinfo=timezone.utc).timestamp() * 1000
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }



@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    employee = db.employees.find_one({"emp_code": body.emp_code})

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    if body.punched_at is None:
        punch_time = datetime.now(timezone.utc)
    else:
        punch_time = datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=timezone.utc
        )

    punch_time = punch_time.replace(microsecond=0)
    
    

    
        
    attendance_date = get_attendance_date(
        punch_time,
        employee["shift_start"],
        employee["shift_end"]
    )

    late_minutes = compute_late_minutes(
        punch_time,
        employee["shift_start"],
        attendance_date
    )

    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": punch_time,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": late_minutes,
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Already punched in for this date"
        )

    return serialize_attendance(doc)



@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    employee = db.employees.find_one({"emp_code": body.emp_code})

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    if body.punched_at is None:
        punch_time = datetime.now(timezone.utc)
    else:
        punch_time = datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=timezone.utc
        )

    punch_time = punch_time.replace(microsecond=0)
    attendance = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$lte": punch_time},
        },
        sort=[("punch_in", -1)],
    )

    if attendance is None:
        raise HTTPException(
            status_code=404,
            detail="No punch-in record found"
        )

    if attendance["punch_out"] is not None:
        raise HTTPException(
            status_code=409,
            detail="Already punched out"
        )
    punch_in_time = attendance["punch_in"].replace(tzinfo=timezone.utc)

    duration = punch_time - punch_in_time

    if duration <= timedelta(0) or duration > timedelta(hours=24):
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in and within 24 hours"
        )
    work_hours = compute_work_hours(punch_in_time, punch_time)

    overtime_minutes = compute_overtime(
        punch_time,
        employee["shift_end"],
        attendance["date"],
        employee["shift_start"],
    )

    half_day = work_hours < 4.50
    updated_attendance = db.attendance_logs.find_one_and_update(
        {
            "_id": attendance["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": punch_time,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
        return_document=ReturnDocument.AFTER,
    )

    if updated_attendance is None:
        raise HTTPException(
            status_code=409,
            detail="Already punched out"
        )

    return serialize_attendance(updated_attendance)
@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[Literal[
        "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
    ]] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from cannot be later than date_to"
        )
    q = {}

    if emp_code:
        q["emp_code"] = emp_code

    if date_from or date_to:
        q["date"] = {}

        if date_from:
            q["date"]["$gte"] = date_from.isoformat()

        if date_to:
            q["date"]["$lte"] = date_to.isoformat()

    if status:
        q["status"] = status

    total = db.attendance_logs.count_documents(q)

    docs = list(
        db.attendance_logs.find(q)
        .sort([("date", -1), ("emp_code", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    items = [serialize_attendance(doc) for doc in docs]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: date,
    body: RegularizeIn,
):
    employee = db.employees.find_one({"emp_code": emp_code})

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    attendance = db.attendance_logs.find_one(
        {
            "emp_code": emp_code,
            "date": date.isoformat(),
        }
    )

    if attendance is None:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found"
        )
    updates = body.model_dump(
        exclude_unset=True,
        exclude={"reason", "regularized_by"},
    )


    new_status = updates.get("status", attendance["status"])
    new_punch_in = attendance.get("punch_in")
    new_punch_out = attendance.get("punch_out")

    if "punch_in" in updates:
        new_punch_in = datetime.fromtimestamp(
            updates["punch_in"] / 1000,
            tz=timezone.utc,
        ).replace(microsecond=0, tzinfo=None)

    if "punch_out" in updates:
        new_punch_out = datetime.fromtimestamp(
            updates["punch_out"] / 1000,
            tz=timezone.utc,
        ).replace(microsecond=0, tzinfo=None)

    # Validate attendance status
    if new_status in ("ABSENT", "LEAVE"):
        if "punch_in" in updates or "punch_out" in updates:
            raise HTTPException(
                status_code=422,
                detail="ABSENT or LEAVE cannot have punch times",
            )

        new_punch_in = None
        new_punch_out = None

    elif new_punch_in is None:
        raise HTTPException(
            status_code=422,
            detail="A presence status requires punch_in",
        )
    if new_punch_in is not None:
        actual_date = get_attendance_date(
            new_punch_in,
            employee["shift_start"],
            employee["shift_end"],
        )

        if actual_date != date.isoformat():
            raise HTTPException(
                status_code=422,
                detail="Punch-in does not belong to attendance date",
            )

    if new_punch_in is not None and new_punch_out is not None:
        duration = (new_punch_out - new_punch_in).total_seconds()

        if duration <= 0 or duration > 24 * 60 * 60:
            raise HTTPException(
                status_code=422,
                detail="Punch-out must be after punch-in and within 24 hours",
            )
    if new_punch_in is not None:
        new_punch_in = new_punch_in.replace(tzinfo=timezone.utc)

    if new_punch_out is not None:
        new_punch_out = new_punch_out.replace(tzinfo=timezone.utc)
    new_late_minutes = 0
    new_work_hours = None
    new_overtime_minutes = 0
    new_half_day = False

    if new_punch_in is not None:
        new_late_minutes = compute_late_minutes(
            new_punch_in,
            employee["shift_start"],
             date.isoformat(),
        )

    if new_punch_in is not None and new_punch_out is not None:
        new_work_hours = compute_work_hours(
            new_punch_in,
            new_punch_out,
        )

        new_overtime_minutes = compute_overtime(
            new_punch_out,
            employee["shift_end"],
            date.isoformat(),
            employee["shift_start"],
        )

        new_half_day = new_work_hours < 4.50

    new_values = {
        "status": new_status,
        "punch_in": new_punch_in,
        "punch_out": new_punch_out,
        "work_hours": new_work_hours,
        "late_minutes": new_late_minutes,
        "overtime_minutes": new_overtime_minutes,
        "half_day": new_half_day,
    }

    changes = {}

    for field, new_value in new_values.items():
        old_value = attendance.get(field)

        comparison_new_value = new_value

        if field in ("punch_in", "punch_out") and new_value is not None:
            comparison_new_value = new_value.replace(tzinfo=None)

        if old_value != comparison_new_value:
            if field in ("punch_in", "punch_out"):
                old_value = (
                    int(old_value.replace(tzinfo=timezone.utc).timestamp() * 1000)
                    if old_value is not None else None
                )

                history_new_value = (
                    int(new_value.timestamp() * 1000)
                    if new_value is not None else None
                )
            else:
                history_new_value = new_value

            changes[field] = {
                "from": old_value,
                "to": history_new_value,
            }
    if not changes:
        raise HTTPException(
            status_code=422,
            detail="No attendance fields changed",
        )
    history_entry = {
        "at": int(datetime.now(timezone.utc).timestamp() * 1000),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes,
    }
    db_values = new_values.copy()

    for field in ("punch_in", "punch_out"):
        if db_values[field] is not None:
            db_values[field] = db_values[field].replace(tzinfo=None)

    updated = db.attendance_logs.find_one_and_update(
        {
            "_id": attendance["_id"],
            "history": attendance.get("history", []),
        },
        {
            "$set": db_values,
            "$push": {"history": history_entry},
        },
        return_document=ReturnDocument.AFTER,
    )

    if updated is None:
        raise HTTPException(
            status_code=409,
            detail="Attendance record was modified concurrently",
        )

    return serialize_attendance(updated)


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(
    emp_code: str,
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
):

    employee = db.employees.find_one({"emp_code": emp_code})

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )
    year, month_number = map(int, month.split("-"))

    month_start = date(year, month_number, 1)

    if month_number == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month_number + 1, 1)

    month_end = next_month - timedelta(days=1)

    joined_on = date.fromisoformat(str(employee["joined_on"]))

    working_start = max(month_start, joined_on)

    working_days = 0
    current_day = working_start

    while current_day <= month_end:
        if current_day.weekday() < 5:
            working_days += 1

        current_day += timedelta(days=1)

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": month_start.isoformat(),
                    "$lte": month_end.isoformat()
                }
            }
        },
        {
            "$addFields": {
                "is_weekday": {
                    "$lte": [
                        {
                            "$isoDayOfWeek": {
                                "$dateFromString": {
                                    "dateString": "$date"
                                }
                            }
                        },
                        5
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$is_weekday",
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"]
                                        ]
                                    }
                                ]
                            },
                            {
                                "$cond": [
                                    {"$ifNull": ["$half_day", False]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0
                        ]
                    }
                },
           
                           "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                            1,
                            0
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": {
                        "$ifNull": ["$late_minutes", 0]
                    }
                },
                           "total_overtime_minutes": {
                    "$sum": {
                        "$ifNull": ["$overtime_minutes", 0]
                    }
                }
            }
        }
    ]

    results = list(db.attendance_logs.aggregate(pipeline))

    summary = results[0] if results else {
        "present_days": 0,
        "leave_days": 0,
        "late_count": 0,
        "total_late_minutes": 0,
        "total_overtime_minutes": 0
    }

    attendance_pct = None

    if working_days > 0:
        attendance_pct = float(
            (
                Decimal(str(summary["present_days"]))
                / Decimal(working_days)
                * Decimal(100)
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )

    return {
    "emp_code": emp_code,
    "month": month,
    "working_days": working_days,
    "present_days": summary["present_days"],
    "leave_days": summary["leave_days"],
    "late_count": summary["late_count"],
    "total_late_minutes": summary["total_late_minutes"],
    "total_overtime_minutes": summary["total_overtime_minutes"],
    "attendance_pct": attendance_pct
}
def build_department_summary_pipeline(month: str, department: str | None = None):
    year, month_number = map(int, month.split("-"))
    month_start = date(year, month_number, 1)

    if month_number == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month_number + 1, 1)

    month_end = next_month - timedelta(days=1)

    pipeline = [
        {
            "$match": {
                "joined_on": {"$lte": month_end.isoformat()}
            }
        }
    ]

    if department is not None:
        pipeline[0]["$match"]["department"] = department

    pipeline.append({
        "$lookup": {
            "from": "attendance_logs",
            "localField": "emp_code",
            "foreignField": "emp_code",
            "as": "attendance"
        }
    })

    pipeline.append({
        "$set": {
            "attendance": {
                "$filter": {
                    "input": "$attendance",
                    "as": "record",
                    "cond": {
                        "$and": [
                            {"$gte": ["$$record.date", month_start.isoformat()]},
                            {"$lte": ["$$record.date", month_end.isoformat()]}
                        ]
                    }
                }
            }
        }
    })

    pipeline.append({
        "$set": {
            "attendance_count": {"$size": {"$ifNull": ["$attendance", []]}}
        }
    })

    pipeline.append({
        "$set": {
            "present_count": {
                "$sum": {
                    "$map": {
                        "input": "$attendance",
                        "as": "record",
                        "in": {
                            "$cond": [
                                {
                                    "$and": [
                                        {
                                            "$lte": [
                                                {
                                                    "$isoDayOfWeek": {
                                                        "$dateFromString": {
                                                            "dateString": "$$record.date"
                                                        }
                                                    }
                                                },
                                                5
                                            ]
                                        },
                                        {
                                            "$in": [
                                                "$$record.status",
                                                ["PRESENT", "WFH", "ON_DUTY"]
                                            ]
                                        }
                                    ]
                                },
                                {
                                    "$cond": [
                                        {"$ifNull": ["$$record.half_day", False]},
                                        0.5,
                                        1
                                    ]
                                },
                                0
                            ]
                        }
                    }
                }
            }
        }
    })

    pipeline.append({
        "$set": {
            "employee_late_count": {
                "$size": {
                    "$filter": {
                        "input": {"$ifNull": ["$attendance", []]},
                        "as": "record",
                        "cond": {
                            "$gt": [
                                {"$ifNull": ["$$record.late_minutes", 0]},
                                0
                            ]
                        }
                    }
                }
            }
        }
    })

    pipeline.append({
        "$set": {
            "employee_late_minutes": {
                "$sum": {
                    "$map": {
                        "input": "$attendance",
                        "as": "record",
                        "in": {"$ifNull": ["$$record.late_minutes", 0]}
                    }
                }
            }
        }
    })

    pipeline.append({
        "$set": {
            "employee_leave_count": {
                "$size": {
                    "$filter": {
                        "input": {"$ifNull": ["$attendance", []]},
                        "as": "record",
                        "cond": {"$eq": ["$$record.status", "LEAVE"]}
                    }
                }
            }
        }
    })

    pipeline.append({
        "$set": {
            "employee_on_duty_count": {
                "$size": {
                    "$filter": {
                        "input": {"$ifNull": ["$attendance", []]},
                        "as": "record",
                        "cond": {"$eq": ["$$record.status", "ON_DUTY"]}
                    }
                }
            }
        }
    })

    pipeline.append({
        "$set": {
            "employee_present_records": {
                "$size": {
                    "$filter": {
                        "input": {"$ifNull": ["$attendance", []]},
                        "as": "record",
                        "cond": {
    "$and": [
        {
            "$in": [
                "$$record.status",
                ["PRESENT", "WFH", "ON_DUTY"]
            ]
        },
        {
            "$ne": ["$$record.work_hours", None]
        }
    ]
}
                    }
                }
            }
        }
    })

    pipeline.append({
        "$set": {
            "employee_total_work_hours": {
                "$sum": {
                    "$map": {
                        "input": "$attendance",
                        "as": "record",
                        "in": {
                            "$cond": [
                                {
                                    "$in": [
                                        "$$record.status",
                                        ["PRESENT", "WFH", "ON_DUTY"]
                                    ]
                                },
                                {"$ifNull": ["$$record.work_hours", 0]},
                                0
                            ]
                        }
                    }
                }
            }
        }
    })
    pipeline.append({
        "$group": {
            "_id": "$department",
            "headcount": {"$sum": 1},
            "total_attendance_records": {"$sum": "$attendance_count"},
            "total_present_records": {"$sum": "$employee_present_records"},
            "present_days": {"$sum": "$present_count"},
            "late_count": {"$sum": "$employee_late_count"},
            "total_late_minutes": {"$sum": "$employee_late_minutes"},
            "leave_count": {"$sum": "$employee_leave_count"},
            "on_duty_count": {"$sum": "$employee_on_duty_count"},
            "total_work_hours": {"$sum": "$employee_total_work_hours"}
        }
    })

    pipeline.append({
        "$set": {
"avg_work_hours": {
    "$cond": [
        {"$gt": ["$total_present_records", 0]},
        {
            "$divide": [
                {
                    "$floor": {
                        "$add": [
                            {
                                "$multiply": [
                                    {
                                        "$divide": [
                                            "$total_work_hours",
                                            "$total_present_records"
                                        ]
                                    },
                                    100
                                ]
                            },
                            0.5
                        ]
                    }
                },
                100
            ]
        },
        None
    ]
}
        }
    })

    pipeline.append({
        "$project": {
            "_id": 0,
            "department": "$_id",
            "headcount": 1,
            "present_days": 1,
            "avg_work_hours": 1,
            "late_count": 1,
            "total_late_minutes": 1,
            "leave_count": 1,
            "on_duty_count": 1
        }
    })

    pipeline.append({
        "$sort": {"department": 1}
    })

    return pipeline

@app.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: str | None = None
):

    pipeline = build_department_summary_pipeline(month, department)
    results = list(db.employees.aggregate(pipeline))
    return {"month": month, "items": results}
def build_late_leaderboard_pipeline(
    month: str,
    department: str | None = None,
    limit: int = 10
):
    year, month_number = map(int, month.split("-"))
    month_prefix = f"{year:04d}-{month_number:02d}"

    pipeline = [
        {
            "$match": {
                "date": {"$regex": f"^{month_prefix}"}
            }
        },
        {
            "$match": {
                "late_minutes": {"$gt": 0}
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "late_count": {"$sum": 1},
                "total_late_minutes": {"$sum": "$late_minutes"}
            }
        },
        {
            "$sort": {
                "total_late_minutes": -1,
                "late_count": -1,
                "_id": 1
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {
            "$unwind": "$employee"
        }
    ]

    if department:
        pipeline.append({
            "$match": {
                "employee.department": department
            }
        })

    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {
                    "total_late_minutes": -1
                },
                "output": {
                    "rank": {"$rank": {}}
                }
            }
        },
        {
            "$match": {
                "rank": {"$lte": limit}
            }
        },
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": {"$toString": "$_id"},
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1
            }
        }
    ])
    pipeline.append({
        "$sort": {
            "total_late_minutes": -1,
            "emp_code": 1
        }
    })

    return pipeline
@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: str | None = None,
    limit: int = Query(10, ge=1, le=50)
):
    pipeline = build_late_leaderboard_pipeline(month, department, limit)
    results = list(db.attendance_logs.aggregate(pipeline))
    return {"month": month, "items": results}
def build_department_trend_pipeline(
    department: str,
    date_from: date,
    date_to: date
):
    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": date_from.isoformat(),
                    "$lte": date_to.isoformat()
                }
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {
            "$unwind": "$employee"
        },
        {
            "$match": {
                "employee.department": department
            }
        },
        {
            "$group": {
                "_id": "$date",
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_minutes", 0]},
                            1,
                            0
                        ]
                    }
                },
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                            {"$cond": ["$half_day", 0.5, 1]},
                            0
                        ]
                    }
                }
            }
        },
        {
            "$sort": {"_id": 1}
        },
        {
            "$addFields": {
                "trend_date": {
                    "$dateFromString": {
                        "dateString": "$_id"
                    }
                }
            }
        },
        {
            "$densify": {
                "field": "trend_date",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [
                        datetime.combine(date_from, datetime.min.time()),
                        datetime.combine(
                            date_to + timedelta(days=1),
                            datetime.min.time()
                        )
                    ]
                }
            }
        },
        {
            "$addFields": {
                "present_count": {"$ifNull": ["$present_count", 0]},
                "late_count": {"$ifNull": ["$late_count", 0]}
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "let": {"day": "$trend_date"},
                "pipeline": [
                    {
                        "$match": {
                            "department": department
                        }
                    },
                    {
                        "$match": {
                            "$expr": {
                                "$lte": [
                                    "$joined_on",
                                    {
                                        "$dateToString": {
                                            "format": "%Y-%m-%d",
                                            "date": "$$day"
                                        }
                                    }
                                ]
                            }
                        }
                    }
                ],
                "as": "joined_employees"
            }
        },
        {
            "$addFields": {
                "headcount": {
                    "$size": "$joined_employees"
                }
            }
        },
        {
            "$addFields": {
                "is_working_day": {
                    "$in": [
                        {"$isoDayOfWeek": "$trend_date"},
                        [1, 2, 3, 4, 5]
                    ]
                }
            }
        },
    {
            "$addFields": {
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                "$is_working_day",
                                {"$gt": ["$headcount", 0]}
                            ]
                        },
                        {
                            "$round": [
                                {"$divide": ["$present_count", "$headcount"]},
                                4
                            ]
                        },
                        None
                    ]
                }
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"trend_date": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {
                            "documents": [-6, 0]
                        }
                    }
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$trend_date"
                    }
                },
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": 1
            }
        }
    ]

    return pipeline
@app.get("/analytics/departments/{department}/trend")
    
def department_trend(
    department: str,
    date_from: date = Query(..., alias="from"),
    date_to: date = Query(..., alias="to")
):
    if date_to < date_from:
        raise HTTPException(
            status_code=422,
            detail="'to' must be on or after 'from'"
        )
    if (date_to - date_from).days + 1 > 92:
        raise HTTPException(
            status_code=422,
            detail="Date range cannot exceed 92 days"
        )
    employee_count = db.employees.count_documents({
        "department": department
    })

    if employee_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Department not found"
        )
    pipeline = build_department_trend_pipeline(
        department, date_from, date_to
    )
   
    results = list(db.attendance_logs.aggregate(pipeline))

    return {
        "department": department,
        "items": results
    }

@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = Query(default=10, ge=1, le=50),
    trend_from: Optional[date] = Query(default=None, alias="from"),
    trend_to: Optional[date] = Query(default=None, alias="to"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    allowed_endpoints = [
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend"
    ]

    if endpoint not in allowed_endpoints:
        raise HTTPException(status_code=422, detail="Invalid endpoint")
    if endpoint == "attendance_list":
        q = {}

        if emp_code:
            q["emp_code"] = emp_code

        if date_from or date_to:
            q["date"] = {}

            if date_from:
                q["date"]["$gte"] = date_from.isoformat()

            if date_to:
                q["date"]["$lte"] = date_to.isoformat()

        if status:
            q["status"] = status
        explain_result = db.command(
            "explain",
            {
                "find": "attendance_logs",
                "filter": q,
                "sort": {"date": -1, "emp_code": 1},
                "skip": (page - 1) * page_size,
                "limit": page_size
            },
            verbosity="executionStats"
        )

        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": explain_result
        }
    if endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(
                status_code=422,
                detail="emp_code and month are required"
            )
        try:
            year, month_number = map(int, month.split("-"))
            month_start = date(year, month_number, 1)

            if month_number == 12:
                month_end = date(year, 12, 31)
            else:
                month_end = date(year, month_number + 1, 1) - timedelta(days=1)

        except (ValueError, TypeError):
            raise HTTPException(
                status_code=422,
                detail="Invalid month. Use YYYY-MM"
            )
        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {
                        "$gte": month_start.isoformat(),
                        "$lte": month_end.isoformat()
                    }
                }
            },
            {
                "$addFields": {
                    "is_weekday": {
                        "$lte": [
                            {
                                "$isoDayOfWeek": {
                                    "$dateFromString": {
                                        "dateString": "$date"
                                    }
                                }
                            },
                            5
                        ]
                    }
                }
            },
                        {
                "$group": {
                    "_id": None,
                    "present_days": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        "$is_weekday",
                                        {
                                            "$in": [
                                                "$status",
                                                ["PRESENT", "WFH", "ON_DUTY"]
                                            ]
                                        }
                                    ]
                                },
                                {
                                    "$cond": [
                                        {"$ifNull": ["$half_day", False]},
                                        0.5,
                                        1
                                    ]
                                },
                                0
                            ]
                        }
                    },
                    "leave_days": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$status", "LEAVE"]},
                                1,
                                0
                            ]
                        }
                    },
                    "late_count": {
                        "$sum": {
                            "$cond": [
                                {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                                1,
                                0
                            ]
                        }
                    },
                    "total_late_minutes": {
                        "$sum": {
                            "$ifNull": ["$late_minutes", 0]
                        }
                    },
                    "total_overtime_minutes": {
                        "$sum": {
                            "$ifNull": ["$overtime_minutes", 0]
                        }
                    }
                }
            }
        ]

        explain_result = db.command(
            "explain",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {}
            },
            verbosity="executionStats"
        )

        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": explain_result
        }
    if endpoint == "department_summary":
        if not month:
            raise HTTPException(status_code=422, detail="month is required")
        try:
            year, month_number = map(int, month.split("-"))
            month_start = date(year, month_number, 1)
            if month_number == 12:
                month_end = date(year, 12, 31)
            else:
                month_end = date(year, month_number + 1, 1) - timedelta(days=1)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Invalid month. Use YYYY-MM")

        pipeline = build_department_summary_pipeline(month, department)
        explain_result = db.command(
            "explain",
            {
                "aggregate": "employees",
                "pipeline": pipeline,
                "cursor": {}
            },
            verbosity="executionStats"
        )

        return {
            "endpoint": endpoint,
            "collection": "employees",
            "explain": explain_result
        }
    if endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required"
            )

        try:
            year, month_number = map(int, month.split("-"))
            date(year, month_number, 1)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=422,
                detail="Invalid month. Use YYYY-MM"
            )

        pipeline = build_late_leaderboard_pipeline(
            month, department, limit
        )

        explain_result = db.command(
            "explain",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {}
            },
            verbosity="executionStats"
        )

        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": explain_result
        }
    if endpoint == "department_trend":
        if not trend_from or not trend_to:
            raise HTTPException(
                status_code=422,
                detail="date_from and date_to are required"
            )

        if trend_to < trend_from:
            raise HTTPException(
                status_code=422,
                detail="'to' must be on or after 'from'"
            )

        if (trend_to - trend_from).days + 1 > 92:
            raise HTTPException(
                status_code=422,
                detail="Date range cannot exceed 92 days"
            )

        if not department:
            raise HTTPException(
                status_code=422,
                detail="department is required"
            )

        if db.employees.count_documents({"department": department}) == 0:
            raise HTTPException(
                status_code=404,
                detail="Department not found"
            )

        pipeline = build_department_trend_pipeline(
            department, trend_from, trend_to
        )
        

        explain_result = db.command(
            "explain",
            {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {}
            },
            verbosity="executionStats"
        )

        return {
            "endpoint": endpoint,
            "collection": "attendance_logs",
            "explain": explain_result
        }

# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#  GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
