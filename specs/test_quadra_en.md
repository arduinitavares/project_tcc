# Technical Specification v5  
## Intelligent Camera System for Counting and Operational Compliance in a Sports Arena

---

## 1. Overview

This document describes the technical specification of a camera-based intelligent system for:

- People counting per court (top-down)
- Flow counting at the complex entrance
- Automatic operational compliance verification
- Integration with scheduling (PDV Pix) and student enrollment (Google Sheets)
- Automatic WhatsApp notifications to the arena manager

### Physical context
- 5 sand courts  
- 1 pickleball court  
- 5 internal cameras (1 per court)  
- 3 cameras at the complex entrance  

---

## 2. System Objectives

1. Measure, in near real time, the occupancy of each court.
2. Compare observed occupancy with expected occupancy according to schedule and rules.
3. Automatically detect:
   - Extra or missing people in classes
   - Use without reservation
   - Improper use of a free court
4. Notify the operational manager via WhatsApp.
5. Support operational exceptions such as court reassignment.

---

## 3. Data Sources

### 3.1 Cameras
- Top-down cameras per court (only the internal court area).
- Cameras at the complex entrance for IN/OUT flow.
- No monitoring of areas outside the courts.

### 3.2 Schedule — PDV Pix
- PDV Pix is the source of **bookings/schedules**.
- Each booking has a boolean field:
  - `is_internal = true` → Instructor-led class
  - `is_internal = false` → Rental
- PDV Pix **does not** provide a list of students per class.

### 3.3 Enrollment and Classes — Google Sheets
Used as a quasi-static source for:
- Students
- Classes (fixed sessions)
- Student enrollments in classes

---

## 4. Court Mode Classification

For each court and time slot, the system defines a `mode`:

- `CLASS`
- `RENTAL`
- `FREE`

### Classification rule
- If `booking.is_internal == true` → `CLASS`
- If `booking.is_internal == false` → `RENTAL`
- If there is no active booking → `FREE`

---

## 5. Spreadsheet Structure (Google Sheets)

### Sheet: `students`
| Field | Description |
|------|------------|
| student_id | Unique identifier |
| full_name | Full name |
| status | ACTIVE / INACTIVE |
| contract_end_date | Optional |

### Sheet: `classes`
| Field | Description |
|------|------------|
| class_id | Class identifier |
| class_name | Class name |
| weekday | Day of the week |
| start_time | Start time |
| end_time | End time |
| default_court_id | Default court |
| instructor_count | Number of instructors |

### Sheet: `enrollments`
| Field | Description |
|------|------------|
| class_id | Class |
| student_id | Student |
| active | TRUE / FALSE |

---

## 6. Class ↔ Booking Association (Join)

For each internal booking (CLASS):

1. Identify day of the week and time.
2. Find a class (`class_id`) with:
   - Same weekday
   - Same time (±5 min tolerance)
3. The court may be adjusted via override (reassignment).

### Expected calculation
- `expected_students_count` = active students in the class
- `expected_total` = `expected_students_count + instructor_count`

---

## 7. Compliance Rules

### Global parameters
- `persist_seconds = 45`
- `cooldown_minutes = 5`

### 7.1 CLASS
- Tolerance: **zero**
- Rule:
  - If `observed_total != expected_total` for `persist_seconds`
- Events:
  - `EXTRA_IN_CLASS`
  - `MISSING_IN_CLASS`

### 7.2 RENTAL
- Quantity does not matter.
- Rule:
  - If `observed_total > 0` and **there is no active booking**
- Event:
  - `USE_WITHOUT_RESERVATION`

### 7.3 FREE
- No one is allowed.
- Rule:
  - If `observed_total > 0`
- Event:
  - `PEOPLE_ON_FREE_COURT`

---

## 8. Court Reassignment (Operational Exception)

### Case
- A class is scheduled, but the court was occupied by a rental.
- The class is moved to another court.

### Entity
`CourtOverride`
- start_datetime
- end_datetime
- from_court_id
- to_court_id
- reason
- created_by
- created_at

### Effect
- Class verification is performed against `to_court_id`.

---

## 9. Computer Vision

### Courts
- One polygon per court.
- Counting via tracking of stable people inside the polygon.

### Entrance
- Virtual IN/OUT lines.
- Generation of flow events.

---

## 10. Notifications (WhatsApp)

- Single recipient (fixed WhatsApp number of the arena).
- Triggered when a `ComplianceEvent` enters the OPEN state.
- Cooldown respected.

### Example message

```
[ALERT] Court 3 — CLASS 11:00–12:00
Expected: 6 (5 students + 1 instructor)
Observed: 7 (+1)
```

---

## 11. Data Model (Summary)

- Court  
- Camera  
- ZoneConfig  
- Booking (PDV Pix)  
- Class  
- Student  
- Enrollment  
- OccupancySnapshot  
- ComplianceEvent  
- CourtOverride  
- NotificationLog  

---

## 12. Internal APIs (Summary)

### Cameras → Backend
POST `/v1/telemetry/occupancy`  
POST `/v1/telemetry/entrance`

### Operations
- GET `/v1/courts/live`
- GET `/v1/events`
- POST `/v1/events/{id}/ack`
- POST `/v1/events/{id}/resolve`
- POST `/v1/overrides`

### Connectors
- `pdvpix_sync`
- `sheets_sync`

---

## 13. Acceptance Criteria (MVP)

1. Per-court counting with update ≤ 5s.
2. Correct alerts for CLASS with zero tolerance.
3. Detection of use without reservation.
4. Functional WhatsApp notifications.
5. Support for manual reassignment.

---

## 14. MVP Out of Scope

- No facial recognition
- No individual identification
- Focus on counting, rules, and operations
- LGPD is not a blocker at this stage

---

End of document.
