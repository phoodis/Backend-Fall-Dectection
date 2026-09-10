# Elderly Surveillance System - API Documentation

## Overview

REST API for elderly monitoring with fall detection, bed exit detection, camera management, and user authentication.

**Base URL:** `http://localhost:8932/api`

**Authentication:** JWT Bearer tokens required for most endpoints

## Table of Contents

1. [Authentication](#authentication)
2. [Admin Management](#admin-management)
3. [Camera Management](#camera-management)
4. [Video Streaming](#video-streaming)
5. [Detection Logs](#detection-logs)
6. [System Logs](#system-logs)
7. [Telegram Integration](#telegram-integration)
8. [Thai FRAT Assessment](#thai-frat-assessment)
9. [Health Check](#health-check)
10. [Error Handling](#error-handling)
11. [Models](#models)

---

## Authentication

### User Roles
- **Admin**: Full access - manage cameras, users, view all data
- **User**: Limited access - view cameras (read-only), create assessments

### POST `/api/auth/register`

Register new user. First user becomes admin automatically.

**Request Body:**
```json
{
  "username": "string",
  "password": "string",
  "role": "admin|user"
}
```

**Response:**
- **201 Created**
```json
{
  "message": "User registered successfully",
  "user": {
    "id": 1,
    "username": "admin",
    "role": "admin",
    "created_at": "2025-09-10T..."
  }
}
```

- **400 Bad Request**
```json
{
  "error": "Both username and password are required to register a new account."
}
```

- **409 Conflict**
```json
{
  "error": "The username \"username\" is already taken. Please choose a different username."
}
```

### POST `/api/auth/login`

**Request Body:**
```json
{
  "username": "string",
  "password": "string"
}
```

**Response:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "user": {
    "id": 1,
    "username": "admin",
    "role": "admin"
  }
}
```

### POST `/api/auth/refresh`

Refresh access token.

**Headers:** `Authorization: Bearer <refresh_token>`

**Response:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "user": {
    "id": 1,
    "username": "admin",
    "role": "admin"
  }
}
```

### GET `/api/auth/verify`

Verify token validity.

**Headers:** `Authorization: Bearer <access_token>`

### POST `/api/auth/logout`

Logout and blacklist current token.

### POST `/api/auth/logout-all`

Logout from all devices.

---

## Admin Management

Admin-only endpoints for user management.

### GET `/api/admin/users`

List all users with statistics.

**Response:**
```json
{
  "users": [
    {
      "id": 1,
      "username": "admin",
      "role": "admin",
      "stats": {
        "total_cameras": 5,
        "active_cameras": 2,
        "total_assessments": 10
      }
    }
  ],
  "total_count": 1
}
```

### POST `/api/admin/users`

Create new user.

**Request Body:**
```json
{
  "username": "string",
  "password": "string",
  "role": "admin|user"
}
```

### PUT `/api/admin/users/{id}`

Update user (cannot change own role).

### DELETE `/api/admin/users/{id}`

Delete user (cannot delete self).

### GET `/api/admin/dashboard`

Admin dashboard statistics.

**Response:**
```json
{
  "users": {
    "total": 10,
    "admins": 2,
    "regular_users": 8
  },
  "cameras": {
    "total": 25,
    "active": 15,
    "inactive": 10
  },
  "assessments": {
    "total": 50
  }
}
```

## Camera Management

### Access Control
- **Admin**: Full CRUD access to all cameras
- **User**: Read-only access to own cameras only

### GET `/api/cameras`

List cameras. Admin sees all cameras with owner info, users see own cameras only.

**Response (Admin):**
```json
[
  {
    "id": 1,
    "name": "Living Room Camera",
    "room_name": "Living Room",
    "url": "rtsp://192.168.1.100:554/stream",
    "detection_type": "fall",
    "is_active": true,
    "alert_start_time": "08:00",
    "alert_end_time": "20:00",
    "notification_cooldown": 600,
    "ai_confidence_threshold": 0.7,
    "owner": {
      "id": 2,
      "username": "user1"
    }
  }
]
```

### POST `/api/cameras`

Add camera (Admin only).

**Request Body:**
```json
{
  "name": "Bedroom Camera",
  "room_name": "Bedroom",
  "url": "rtsp://192.168.1.101:554/stream",
  "detection_type": "bed_exit|fall|fall_v2",
  "owner_id": 2,
  "alert_start_time": "08:00",
  "alert_end_time": "20:00",
  "notification_cooldown": 600,
  "ai_confidence_threshold": 0.5
}
```

### PUT `/api/cameras/{id}`

Update camera (Admin only).

### DELETE `/api/cameras/{id}`

Delete camera (Admin only).

### GET `/api/cameras/{id}`

Get camera details. Admin can view any camera, users can view own cameras only.

### GET `/api/cameras/{id}/status`

Get camera detection status.

### POST `/api/cameras/{id}/start`

Start camera monitoring.

### POST `/api/cameras/{id}/stop`

Stop camera monitoring.

---

## Video Streaming

MJPEG video streaming from cameras.

### GET `/api/stream/camera/{id}`

Stream live video as MJPEG.

**Response:** `Content-Type: multipart/x-mixed-replace; boundary=frame`

### POST `/api/stream/camera/{id}/start`

Start camera stream.

### POST `/api/stream/camera/{id}/stop`

Stop camera stream.

### GET `/api/stream/camera/{id}/status`

Get stream status and statistics.

### GET `/api/stream/stats`

Get statistics for all active streams.

## Detection Logs

30-day retention for camera detection events.

### Detection Types

**Original Models:**
- `bed_exit`: Bed exit detection using ONNX model
- `fall`: Fall detection using ONNX model + person tracking

**V2 Models (ONNX Optimized):**
- `fall_v2`: Enhanced fall detection using ONNX DeepSVDD model
  - Uses combined RGB (ResNet50) + Optical Flow + Pose features (2420 features total)
  - RGB features: 2048 (extracted from ResNet50 pretrained model)
  - Optical Flow features: 236 (temporal motion information)  
  - Pose features: 136 (MediaPipe keypoint data)
  - ONNX Runtime for faster inference (2-3x speedup vs PyTorch)
  - Higher accuracy with threshold 0.285
  - Runs two parallel tasks: fall detection + person counting
  - Produces separate `fall_v2` and `alone_v2` detection logs

### Model Selection
- Use `fall` for standard detection
- Use `fall_v2` for enhanced accuracy
- Both models support person counting for alone detection

### Detection Results
- `fall`: Fall detected (original model)
- `fall_v2`: Fall detected (V2 model)
- `alone`: Person alone in frame (original model)
- `alone_v2`: Person alone in frame (V2 model)
- `normal`: Multiple persons or normal activity
- `no_person`: No person detected
- `bed_exit`: Person exited bed

### GET `/api/detection-logs`

Get today's detection logs from user's cameras.

**Response:**
```json
[
  {
    "id": 1,
    "timestamp": "2024-01-15T14:30:25.123456",
    "camera_id": 1,
    "detection_result": "fall",
    "confidence_score": 0.85,
    "camera_name": "Living Room Camera",
    "room_name": "Living Room",
    "risk_level": "red",
    "person_count": 1
  }
]
```

### GET `/api/detection-logs/{camera_id}`

Get detection logs for specific camera.

### GET `/api/detection-logs/notifications`

Get notification history.

---

## System Logs

90-day retention for system events.

### GET `/api/system-logs`

**Query Parameters:**
- `page`: Page number (default: 1)
- `per_page`: Items per page (default: 50, max: 100)  
- `level`: Filter by log level (INFO, WARNING, ERROR, CRITICAL)
- `component`: Filter by component (AUTH, CAMERA, DETECTION)

**Response:**
```json
{
  "logs": [
    {
      "id": 1,
      "timestamp": "2024-01-15T14:30:25+07:00",
      "level": "INFO",
      "message": "User logged in: admin",
      "component": "AUTH",
      "user_id": 1
    }
  ],
  "total": 50,
  "pages": 5,
  "current_page": 1
}
```

## Telegram Integration

Per-user Telegram settings for notifications.

### GET `/api/telegram/settings`

Get current user's Telegram settings.

**Headers:** `Authorization: Bearer <access_token>`

**Response:**
```json
{
  "success": true,
  "data": {
    "id": 1,
    "user_id": 2,
    "bot_token": "123456789:ABC...",
    "chat_id": "-100123456789",
    "created_at": "2024-01-15T10:00:00+07:00",
    "updated_at": "2024-01-15T10:30:00+07:00"
  }
}
```

### POST `/api/telegram/settings`

Update current user's Telegram settings.

**Headers:** `Authorization: Bearer <access_token>`

**Request Body:**
```json
{
  "bot_token": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
  "chat_id": "-100123456789"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Telegram settings updated successfully",
  "data": {
    "id": 1,
    "user_id": 2,
    "bot_token": "123456789:ABC...",
    "chat_id": "-100123456789"
  }
}
```

### POST `/api/telegram/test`

Test current user's Telegram settings.

**Headers:** `Authorization: Bearer <access_token>`

**Response:**
```json
{
  "success": true,
  "message": "Test message sent successfully!"
}
```

---

## Thai FRAT Assessment

Thai Fall Risk Assessment Tool for elderly fall risk evaluation.

### Scoring
- **Q1 (Fall History)**: 0 or 25 points
- **Q2 (Secondary Diagnosis)**: 0 or 15 points  
- **Q3 (Ambulatory Aid)**: 0, 15, or 30 points
- **Q4 (IV/Heparin)**: 0 or 25 points
- **Q5 (Gait/Transfer)**: 0, 10, or 20 points
- **Q6 (Mental State)**: 0 or 15 points

### Risk Levels
- **Low (0-24)**: Low fall risk
- **Medium (25-50)**: Moderate fall risk
- **High (≥51)**: High fall risk

### Access Control
- **Admin**: Can view all assessments, create assessments for any user
- **User**: Can create assessments, view own assessments and shared ones

### GET `/api/thai-frat/assessments`

Get assessments. Admin sees all with creator info, users see own and shared.

**Response (User):**
```json
{
  "own_assessments": [
    {
      "id": 1,
      "creator_id": 1,
      "name": "John Doe",
      "tel": "0812345678",
      "pdpa_consent": true,
      "q1_score": 25,
      "q1_value": "เคย",
      "total_score": 50,
      "risk_level": "medium",
      "created_at": "2024-01-15T10:00:00+07:00"
    }
  ],
  "shared_assessments": []
}
```

### POST `/api/thai-frat/assessments`

Create new assessment. Both admin and users can create.

**Request Body:**
```json
{
  "name": "John Doe",
  "tel": "0812345678",
  "province": "Bangkok",
  "pdpa_consent": true,
  "q1": 25,
  "q2": 15,
  "q3": 0,
  "q4": 0,
  "q5": 10,
  "q6": 0,
  "creator_id": 2
}
```

### GET `/api/thai-frat/assessments/{id}`

Get specific assessment (owner or shared access).

### PUT `/api/thai-frat/assessments/{id}`

Update assessment (owner only).

### DELETE `/api/thai-frat/assessments/{id}`

Delete assessment (owner only).

### POST `/api/thai-frat/assessments/{id}/share`

Share assessment with another user.

**Request Body:**
```json
{
  "username": "nurse1",
  "include_personal_info": true
}
```

### GET `/api/thai-frat/question-options`

Get question options and scoring (no auth required).

---

## Health Check

### GET `/api/health`

Server health check.

### GET `/api/health/camera-detection-service`

Camera detection service status.

---

## Error Handling

Standard HTTP status codes with JSON error messages.

### Common Errors

- **400 Bad Request**: `{"error": "Description"}`
- **401 Unauthorized**: `{"msg": "Missing Authorization Header"}`  
- **403 Forbidden**: `{"error": "Access denied"}`
- **404 Not Found**: `{"error": "Resource not found"}`
- **409 Conflict**: `{"error": "Resource already exists"}`
- **500 Internal Server Error**: `{"error": "Internal server error"}`

---

## Models

### User
```json
{
  "id": "integer",
  "username": "string",
  "role": "admin|user",
  "created_at": "datetime"
}
```

### Camera
```json
{
  "id": "integer",
  "name": "string",
  "room_name": "string",
  "url": "string",
  "detection_type": "bed_exit|fall|fall_v2",
  "is_active": "boolean",
  "alert_start_time": "string",
  "alert_end_time": "string",
  "notification_cooldown": "integer",
  "ai_confidence_threshold": "float",
  "owner": {
    "id": "integer",
    "username": "string"
  }
}
```

### Detection Log
```json
{
  "id": "integer",
  "timestamp": "datetime",
  "camera_id": "integer",
  "detection_result": "fall|fall_v2|alone|alone_v2|normal|no_person|bed_exit",
  "confidence_score": "float",
  "camera_name": "string",
  "room_name": "string",
  "risk_level": "normal|yellow|red",
  "person_count": "integer"
}
```

### Thai FRAT Assessment
```json
{
  "id": "integer",
  "creator_id": "integer",
  "name": "string",
  "tel": "string",
  "province": "string",
  "pdpa_consent": "boolean",
  "q1_score": "integer",
  "q1_value": "string",
  "total_score": "integer",
  "risk_level": "low|medium|high",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```

### Telegram Settings
```json
{
  "id": "integer",
  "user_id": "integer",
  "bot_token": "string",
  "chat_id": "string",
  "created_at": "datetime",
  "updated_at": "datetime"
}
```
