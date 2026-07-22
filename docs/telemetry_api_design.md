# Server-Side Telemetry Web API: System Status Collector

_Last updated: 2026-07-22_

This document outlines the API design for a server-side telemetry collector. It collects client-side real-time system metrics (CPU, Memory PSS, Native Heap, Tokens/s, GPU utilization, and Thermal Status) paired with unique **Session IDs** from the on-device Gemma application for further performance and resource consumption analysis.

---

## Data Schema Reference

Each telemetry metric sample uploaded from the Android client maps to the following structured schema:

```json
{
  "timestamp": "2026-07-22T03:45:00.123Z", // ISO-8601 UTC timestamp
  "cpu_percent": 45.2,                   // Process CPU % (Float)
  "total_pss_mb": 420.5,                 // Proportional Set Size in MB (Float)
  "native_heap_mb": 310.2,               // Native Heap usage in MB (Float)
  "tokens_per_second": 12.5,             // Generation throughput in tok/s (Float)
  "gpu_percent": 18.0,                   // GPU load % (Float, optional/nullable if CPU execution)
  "thermal_status": "Normal"             // String (Normal, Light Heat, Moderate, Throttled, Critical)
}
```

---

## Web API Endpoints

### 1. Add/Append System Status (Batch Upload)
Submit a batch of telemetry metric samples accumulated locally over a window of time (e.g., buffering every 10–30 seconds before uploading). If the `session_id` does not exist in the database, the server initializes a new telemetry session and adds all samples. If the `session_id` already exists, the server appends the array of samples to the existing session history.

- **Endpoint**: `POST /api/telemetry/status`
- **Content-Type**: `application/json`
- **Request Body**:
  ```json
  {
    "session_id": "a33f0ccc-b447-4140-92e1-d22f2cd523f5",
    "model_id": "gemma4-e2b-it-cpu", // Useful context about the running model & target backend
    "samples": [
      {
        "timestamp": "2026-07-22T03:45:00.000Z",
        "cpu_percent": 34.5,
        "total_pss_mb": 412.3,
        "native_heap_mb": 298.1,
        "tokens_per_second": 11.2,
        "gpu_percent": null,
        "thermal_status": "Normal"
      },
      {
        "timestamp": "2026-07-22T03:45:01.000Z",
        "cpu_percent": 36.1,
        "total_pss_mb": 412.5,
        "native_heap_mb": 298.1,
        "tokens_per_second": 11.8,
        "gpu_percent": null,
        "thermal_status": "Normal"
              }
    ]
  }
  ```
- **Response** (`200 OK` or `201 Created`):
  ```json
  {
    "status": "success",
    "message": "Batch of 2 telemetry samples appended",
    "session_id": "a33f0ccc-b447-4140-92e1-d22f2cd523f5",
    "total_samples": 42
  }
  ```
- **Response** (`400 Bad Request` if payload violates constraints):
  ```json
  {
    "status": "error",
    "message": "Invalid payload: missing session_id, model_id, or samples array"
  }
  ```

---

### 2. List All Session IDs
Retrieve a list of all active or historical session IDs currently tracked in the database, along with key metadata summarizing each session.

- **Endpoint**: `GET /api/telemetry/sessions`
- **Query Parameters (Optional)**:
  - `limit`: Number of sessions to return (integer, default: 50, e.g. `?limit=100`)
  - `offset`: Offset index for pagination (integer, default: 0, e.g. `?offset=50`)
- **Response** (`200 OK`):
  ```json
  {
    "status": "success",
    "total_sessions": 3,
    "sessions": [
      {
        "session_id": "a33f0ccc-b447-4140-92e1-d22f2cd523f5",
        "model_id": "gemma4-e2b-it-cpu",
        "sample_count": 42,
        "created_at": "2026-07-22T03:12:00.000Z",
        "last_updated_at": "2026-07-22T03:45:00.123Z"
      },
      {
        "session_id": "1c0b899e-c4c8-4782-abea-596a738c1e5f",
        "model_id": "gemma3-1b-it-gpu",
        "sample_count": 120,
        "created_at": "2026-07-22T02:00:10.000Z",
        "last_updated_at": "2026-07-22T02:02:10.000Z"
      }
    ]
  }
  ```

---

### 3. Get Data for a Specified Session
Retrieve the full telemetry history, metadata, and calculated summary metrics for a given unique session ID.

- **Endpoint**: `GET /api/telemetry/sessions/{session_id}`
- **Response** (`200 OK`):
  ```json
  {
    "status": "success",
    "session_id": "a33f0ccc-b447-4140-92e1-d22f2cd523f5",
    "model_id": "gemma4-e2b-it-cpu",
    "created_at": "2026-07-22T03:12:00.000Z",
    "last_updated_at": "2026-07-22T03:45:00.123Z",
    "sample_count": 42,
    "aggregations": {
      "avg_cpu_percent": 41.2,
      "max_cpu_percent": 115.4,
      "avg_total_pss_mb": 415.8,
      "max_total_pss_mb": 428.1,
      "avg_native_heap_mb": 301.4,
      "max_native_heap_mb": 312.5,
      "avg_tokens_per_second": 11.5,
      "max_tokens_per_second": 12.8,
      "throttled_samples_count": 0
    },
    "history": [
      {
        "timestamp": "2026-07-22T03:12:01.000Z",
        "cpu_percent": 12.1,
        "total_pss_mb": 150.2,
        "native_heap_mb": 45.3,
        "tokens_per_second": 0.0,
        "gpu_percent": null,
        "thermal_status": "Normal"
      },
      {
        "timestamp": "2026-07-22T03:12:02.000Z",
        "cpu_percent": 84.5,
        "total_pss_mb": 410.1,
        "native_heap_mb": 295.4,
        "tokens_per_second": 10.8,
        "gpu_percent": null,
        "thermal_status": "Normal"
      }
    ]
  }
  ```
- **Response** (`404 Not Found` if the session ID is unrecognized):
  ```json
  {
    "status": "error",
    "message": "Session ID not found"
  }
  ```

---

## Suggested DB Schema (PostgreSQL DDL)

If you implement this on a relational database like PostgreSQL, here is a highly optimized DDL design utilizing a parent-child table relationship:

```sql
-- Parent Table: Stores unique client-side sessions
CREATE TABLE IF NOT EXISTS telemetry_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    model_id VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Child Table: Stores high-frequency metric samples partitioned or linked by session_id
CREATE TABLE IF NOT EXISTS telemetry_samples (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL REFERENCES telemetry_sessions(session_id) ON DELETE CASCADE,
    client_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    cpu_percent REAL NOT NULL,
    total_pss_mb REAL NOT NULL,
    native_heap_mb REAL NOT NULL,
    tokens_per_second REAL NOT NULL,
    gpu_percent REAL,
    thermal_status VARCHAR(50) NOT NULL,
    server_received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast sample history lookup per session sorted by chronological order
CREATE INDEX IF NOT EXISTS idx_telemetry_samples_session_time 
ON telemetry_samples (session_id, client_timestamp ASC);
```

---

## Client Integration Note (Android Retrofit Example)

To integrate this in your Android client, define the following Retrofit service interface:

```kotlin
interface TelemetryApiService {
    @POST("api/telemetry/status")
    suspend fun uploadTelemetryBatch(
        @Body payload: TelemetryPayload
    ): Response<TelemetryResponse>
}

data class TelemetryPayload(
    val session_id: String,
    val model_id: String,
    val samples: List<TelemetrySample>
)

data class TelemetrySample(
    val timestamp: String, // ISO UTC string
    val cpu_percent: Float,
    val total_pss_mb: Float,
    val native_heap_mb: Float,
    val tokens_per_second: Float,
    val gpu_percent: Float?,
    val thermal_status: String
)

data class TelemetryResponse(
    val status: String,
    val message: String,
    val session_id: String,
    val total_samples: Int
)
```
