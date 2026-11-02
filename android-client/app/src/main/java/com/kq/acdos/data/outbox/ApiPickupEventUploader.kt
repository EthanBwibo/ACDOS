package com.kq.acdos.data.outbox

import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.MeApi
import com.kq.acdos.data.remote.PickupEventBatchDto
import com.kq.acdos.data.remote.PickupEventInDto
import com.kq.acdos.data.remote.PickupEventOutcomeDto
import com.kq.acdos.data.remote.PickupEventResultDto
import com.kq.acdos.data.remote.PickupEventTypeDto
import com.kq.acdos.data.remote.PickupExceptionTypeDto
import com.kq.acdos.data.remote.apiCall

/** [PickupEventUploader] over POST /drivers/me/pickup-events (#33). */
class ApiPickupEventUploader(private val api: MeApi) : PickupEventUploader {
    override suspend fun upload(events: List<PendingPickupEventEntity>): BatchResult {
        val batch = PickupEventBatchDto(events.map { it.toDto() })
        return when (val result = apiCall { api.uploadPickupEvents(batch) }) {
            is ApiResult.Success -> BatchResult.Answered(
                result.body.results.associate { it.idempotencyKey to it.outcome() }
            )

            // Whole-request errors: 401 and 5xx can pass, so the batch waits. A
            // 403 or 422 won't, but the events stay on the phone either way.
            is ApiResult.NetworkError, is ApiResult.Error -> BatchResult.Retry
        }
    }
}

internal fun PendingPickupEventEntity.toDto() = PickupEventInDto(
    idempotencyKey = idempotencyKey,
    routeNodeId = routeNodeId,
    driverId = driverId,
    eventType = when (eventType) {
        PickupEventType.PICKUP_CONFIRMED -> PickupEventTypeDto.PICKUP_CONFIRMED
        PickupEventType.EXCEPTION -> PickupEventTypeDto.EXCEPTION
    },
    exceptionType = when (exceptionType) {
        PickupExceptionType.NO_SHOW -> PickupExceptionTypeDto.NO_SHOW
        PickupExceptionType.VEHICLE_ISSUE -> PickupExceptionTypeDto.VEHICLE_ISSUE
        PickupExceptionType.TRAFFIC_DELAY -> PickupExceptionTypeDto.TRAFFIC_DELAY
        null -> null
    },
    occurredAt = confirmedAt
)

/** accepted and duplicate are both success; rejected keeps the code, e.g. already_confirmed. */
internal fun PickupEventResultDto.outcome(): UploadResult = when (status) {
    PickupEventOutcomeDto.ACCEPTED, PickupEventOutcomeDto.DUPLICATE -> UploadResult.Synced
    PickupEventOutcomeDto.REJECTED -> UploadResult.Rejected(code.name.lowercase())
}
