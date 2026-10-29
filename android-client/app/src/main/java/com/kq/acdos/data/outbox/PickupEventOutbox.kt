package com.kq.acdos.data.outbox

import com.kq.acdos.data.local.PendingPickupEventDao
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import java.time.Clock
import java.util.UUID

/** How the server answered one upload. Mapping HTTP responses to these is the uploader's job. */
sealed interface UploadResult {
    data object Accepted : UploadResult

    /** The idempotency_key already exists: an earlier attempt got through. */
    data object DuplicateKey : UploadResult

    /** pickup_events_one_confirmation_per_node: the stop was already confirmed. */
    data object AlreadyConfirmed : UploadResult

    /**
     * Any other refusal that retrying cannot fix, e.g. RLS 403 or a route node
     * gone after a re-plan. [reason] is stored as the conflict.
     */
    data class Rejected(val reason: String) : UploadResult

    /** Network or server trouble; try again later. */
    data object Retry : UploadResult
}

/**
 * Sends one event to the API. Implemented with Retrofit in #26, which sends
 * [PendingPickupEventEntity.driverId] as stored, not the current session's user.
 */
fun interface PickupEventUploader {
    suspend fun upload(event: PendingPickupEventEntity): UploadResult
}

/**
 * Records pickup events on the device and uploads them when there is signal.
 * [currentUserId] is the signed-in user's id, or null when nobody is signed in.
 */
class PickupEventOutbox(
    private val dao: PendingPickupEventDao,
    private val uploader: PickupEventUploader,
    private val currentUserId: suspend () -> String?,
    private val clock: Clock = Clock.systemUTC(),
    private val newKey: () -> String = { UUID.randomUUID().toString() }
) {
    suspend fun recordConfirmation(routeNodeId: String): String =
        record(routeNodeId, PickupEventType.PICKUP_CONFIRMED, null)

    suspend fun recordException(routeNodeId: String, type: PickupExceptionType): String =
        record(routeNodeId, PickupEventType.EXCEPTION, type)

    private suspend fun record(
        routeNodeId: String,
        type: PickupEventType,
        exceptionType: PickupExceptionType?
    ): String {
        val driverId = checkNotNull(currentUserId()) { "No signed-in driver to record for" }
        val key = newKey()
        dao.insert(
            PendingPickupEventEntity(
                idempotencyKey = key,
                driverId = driverId,
                routeNodeId = routeNodeId,
                eventType = type,
                exceptionType = exceptionType,
                confirmedAt = clock.instant()
            )
        )
        return key
    }

    /**
     * Uploads the signed-in user's pending events, oldest first. Another user's
     * events wait until that user signs in again. Stops at the first
     * [UploadResult.Retry], since the next one would most likely fail the same
     * way. Returns how many of this user's events are still pending.
     */
    suspend fun uploadPending(): Int {
        val driverId = currentUserId() ?: return 0
        val pending = dao.pending(driverId)
        for ((index, event) in pending.withIndex()) {
            when (val result = uploader.upload(event)) {
                UploadResult.Accepted, UploadResult.DuplicateKey ->
                    dao.markSynced(event.idempotencyKey, clock.instant())

                // Terminal: retrying can never succeed, so it is shown to the driver
                // instead, and the events behind it still go.
                UploadResult.AlreadyConfirmed ->
                    dao.markConflict(event.idempotencyKey, CONFLICT_ALREADY_CONFIRMED)

                is UploadResult.Rejected -> dao.markConflict(event.idempotencyKey, result.reason)

                UploadResult.Retry -> return pending.size - index
            }
        }
        return 0
    }

    companion object {
        const val CONFLICT_ALREADY_CONFIRMED = "stop_already_confirmed"
    }
}
