# DECISIONS.md  (about 150-200 words in total - plain language, your own words)
# Implementation Decisions

1. Indexes

I created unique indexes on `employees.emp_code` and `attendance_logs(emp_code, date)` to prevent duplicates. I added `employees(department, joined_on)` for department queries and `attendance_logs(date DESC, emp_code)` for attendance listing. I considered a separate index on `late_minutes`, but did not add it because the leaderboard also filters by month.

2. Punch-in race

If two identical requests arrive together, both may reach the insert operation. MongoDB's unique index allows only one record for that employee and date. The successful request returns 201. The other receives a `DuplicateKeyError`, which my code converts to HTTP 409.

3. Ties

I use MongoDB's `$rank` based on total late minutes. Employees with equal totals receive the same rank. If they tie at the limit, both are returned because the pipeline filters by rank, not by number of rows.

4. Headcount

The department summary starts from the `employees` collection and looks up attendance records. This includes employees with no attendance logs in the headcount.

5. Scaling

For 100 times more data, I would optimize the department summary lookup to filter attendance records by date inside MongoDB, reducing unnecessary data processing.