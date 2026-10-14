# Employee Attendance Management API

A REST API built using **FastAPI, Python, and MongoDB** for managing employees, tracking attendance, and generating attendance analytics.

## Features

- Employee creation and listing with validation and pagination.
- Attendance punch-in and punch-out.
- Late arrival calculation with a 10-minute grace period.
- Work hours, overtime, and half-day calculations.
- Overnight shift support.
- Attendance regularization with change history.
- Monthly employee attendance analytics.
- Department-wise attendance summaries and daily trends.
- Late arrival leaderboard with ranking.
- MongoDB Explain endpoint for query performance inspection.

## Requirements

- Python 3.10 or newer
- MongoDB 6.0 or newer
- pip

## Setup

### 1. Create a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure MongoDB

Create a `.env` file in the project root and set the MongoDB connection:

```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

For a local MongoDB Docker container, ensure MongoDB is running on port `27017`.

### 4. Load sample data (optional)

```powershell
python sample_seed.py
```

### 5. Start the API

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

The API runs at:

http://127.0.0.1:8000

## API Documentation

Swagger UI:

http://127.0.0.1:8000/docs

OpenAPI JSON:

http://127.0.0.1:8000/openapi.json

## Main API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/employees` | Create employee |
| GET | `/employees` | List employees |
| POST | `/attendance/punch-in` | Record punch-in |
| POST | `/attendance/punch-out` | Record punch-out |
| GET | `/attendance` | List attendance records |
| PATCH | `/attendance/{emp_code}/{date}` | Regularize attendance |
| GET | `/analytics/employees/{emp_code}/monthly` | Monthly employee summary |
| GET | `/analytics/departments/summary` | Department summary |
| GET | `/analytics/leaderboard/late` | Late arrival leaderboard |
| GET | `/analytics/departments/{department}/trend` | Department attendance trend |
| GET | `/admin/explain/{endpoint}` | MongoDB query execution plan |

## Testing

Start MongoDB and the FastAPI server, then open Swagger UI.

Test the endpoints using the **Try it out** option.

The implementation has been manually tested for employee validation, attendance operations, late grace-period boundaries, overtime, half-day calculation, overnight shifts, attendance regularization, and analytics responses.

MongoDB Explain was also checked for index usage in attendance listing, employee monthly analytics, department summary, and late leaderboard queries.

## Project Files

- `app/main.py` — API implementation
- `requirements.txt` — Python dependencies
- `openapi.yaml` — Provided API contract
- `DATA_MODEL.md` — Data model documentation
- `DECISIONS.md` — Implementation decisions
- `REVIEW.md` — Review documentation
- `sample_seed.py` — Sample data loader
- `sample_data/` — Sample MongoDB documents

## Submission

Submit a public Git repository containing the application code and required documentation.

Do not commit `.env`, credentials, virtual environments, or secrets.