# Code Review — Starter Defects and Fixes

I reviewed the starter `app/main.py`, fixed defects in the existing helpers and endpoints, and implemented the missing API endpoints according to the provided contract.

## Defects found in the starter code

| # | Where (function / area) | What is wrong | How you'd notice it (test, input, or symptom) | How I fixed it |
|---|---|---|---|---|
| 1 | Database initialization | Required MongoDB indexes were missing. Duplicate employee codes or attendance records could be inserted during concurrent requests. | Send two requests with the same employee code or punch-in date. | Added unique indexes on employee code and employee/date, plus indexes for common queries. |
| 2 | `compute_late_minutes` | It used the punch-in date and time without correctly handling IST and overnight shifts. | Test a night shift or timestamps near midnight. | Calculated the shift start using the attendance date in IST and applied the 10-minute grace period. |
| 3 | `compute_work_hours` | Python's default `round()` may not follow the required half-up rounding rule. | Test a duration that falls exactly on a rounding boundary. | Used `Decimal` with `ROUND_HALF_UP` to return two decimal places. |
| 4 | `compute_overtime` | It did not handle overnight shift end dates and returned overtime even below the 30-minute threshold. | Test a 22:00–06:00 shift or punching out 20 minutes after shift end. | Handled overnight shift dates in IST and returned zero overtime when below 30 minutes. |
| 5 | `EmployeeIn` | Employee code, name, email, department, shift times, and joining date lacked sufficient validation. | Submit an invalid employee code, malformed email, or invalid shift time. | Added Pydantic field validation and a check that shift start and end differ. |
| 6 | `PunchInIn` | Timestamp and attendance status were not strictly validated. | Submit an unsupported status or invalid timestamp. | Added timestamp constraints and allowed status values. |
| 7 | `health` | It returned success without checking MongoDB connectivity. | Stop MongoDB and call `/health`; the starter would still report OK. | Added a MongoDB ping and returned HTTP 503 when the database is unavailable. |
| 8 | `create_employee` | Duplicate detection used a separate lookup before insertion, which is not safe for concurrent requests. The creation timestamp was also not returned in the required millisecond format. | Send concurrent duplicate requests or inspect the response timestamp. | Used a unique index, caught `DuplicateKeyError` as HTTP 409, and returned UTC epoch milliseconds. |
| 9 | `list_employees` | Pagination used `page * page_size`, skipping the first page. | Request page 1 with a small page size. | Changed the offset to `(page - 1) * page_size`. |
| 10 | `list_employees` | The total count ignored the department filter. | Filter by department and compare `total` with matching employees. | Applied the same filter to `count_documents()`. |
| 11 | `list_employees` | Pagination lacked proper parameter bounds and stable sorting. | Try page 0 or request consecutive pages. | Added query validation and sorted by employee code before pagination. |
| 12 | `punch_in` | An unknown employee could cause a server error because the code accessed the missing employee record. | Punch in using a nonexistent employee code. | Added an employee existence check returning HTTP 404. |
| 13 | `punch_in` | It used the local system date instead of the attendance date in IST and did not correctly support overnight shifts. | Test a timestamp near midnight or an overnight shift. | Added `get_attendance_date()` to determine the correct attendance date. |
| 14 | `punch_in` | It used a separate duplicate lookup before insertion, which could allow concurrent duplicates. | Send duplicate punch-in requests for the same employee and date. | Used a unique MongoDB index and handled duplicate insertion with HTTP 409. |
| 15 | `punch_in` | Timestamp handling and response serialization were inconsistent with the required epoch-millisecond format. | Supply a timestamp with milliseconds and inspect the stored and returned values. | Converted timestamps to UTC, normalized to whole seconds, and added attendance serialization. |
| 16 | `list_attendance` | It loaded all matching attendance records into Python and sorted and paginated them in memory. | Query a large attendance dataset. | Moved sorting, skipping, and limiting into MongoDB. |
| 17 | `list_attendance` | Date ranges, status values, and pagination parameters were not fully validated. | Send an invalid date range or page size. | Added typed date parameters, allowed status values, and pagination bounds. |
| 18 | `list_attendance` | The response included MongoDB-specific handling instead of consistently returning the required attendance fields and timestamp format. | Inspect returned attendance records. | Reused `serialize_attendance()` to format responses consistently. |

## Missing endpoints implemented

The starter file also contained TODO comments for endpoints that had not been implemented. I completed the following:

| Endpoint | Implementation |
|---|---|
| `POST /attendance/punch-out` | Validates the employee and punch-in record, prevents duplicate punch-outs, checks the 24-hour limit, and calculates work hours, overtime, and half-day status. |
| `PATCH /attendance/{emp_code}/{date}` | Supports attendance regularization, validates changes, recalculates derived fields, and records change history. |
| `GET /analytics/employees/{emp_code}/monthly` | Calculates working days, attendance percentage, late counts, leave days, and overtime totals using MongoDB aggregation. |
| `GET /analytics/departments/summary` | Produces department-level attendance statistics using MongoDB aggregation. |
| `GET /analytics/leaderboard/late` | Ranks employees by late minutes using MongoDB aggregation and window functions. |
| `GET /analytics/departments/{department}/trend` | Produces daily attendance trends, including missing dates and a seven-day moving average. |
| `GET /admin/explain/{endpoint}` | Returns MongoDB execution plans and statistics for supported queries. |

## Reviewed but not considered defects

- **FastAPI framework setup:** The starter already created a valid FastAPI application, so I kept that structure.
- **MongoDB environment configuration:** The starter already supported `MONGO_URI` and `MONGO_DB`, so I retained this approach.
- **10-minute grace-period rule:** The starter's condition that lateness within 10 minutes should count as zero was correct. I kept the rule while correcting timezone and shift-date handling.
- **Basic employee department filtering:** The starter already filtered employee results by department. The actual defect was that the total count did not use the same filter.
- **Attendance filter structure:** The starter already supported employee, date, and status filters. I kept those filters while improving validation, sorting, pagination, and serialization.

## Verification

I tested the implemented API through FastAPI Swagger UI, including successful requests and validation errors.

The checks included duplicate employees, duplicate punch-ins and punch-outs, late-arrival boundaries, half-day and overtime calculations, overnight shifts, attendance regularization, monthly analytics, department summaries, trends, and the late leaderboard.

I also used MongoDB Explain to inspect index usage and query execution for attendance listing and analytics endpoints.