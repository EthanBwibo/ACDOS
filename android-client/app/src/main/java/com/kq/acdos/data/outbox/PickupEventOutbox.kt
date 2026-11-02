package com.kq.acdos.data.outbox

import com.kq.acdos.data.local.PendingPickupEventDao
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import java.time.Clock
import java.util.UUID
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** How the server answered one event of a batch. */
sealed interface UploadResult {
    /** accepted, or duplicate: an earlier upload already got through. */
    data object Synced : UploadResult

    /** Refused for good, e.g. already_confirmed. [code] is stored as the conflict. */
    data class Rejected(val code: String) : UploadResult
}

/** How the server answered a whole batch. */
sealed interface BatchResult {
    /** Per event, by idempotency key. An event missing from the map stays pending. */
    data class Answered(val byKey: Map<String, UploadResult>) : BatchResult

    /**
     * No answer, a 5xx, or a 401 the token refresh couldn't fix: send the whole
     * batch again later. The keys make a resend come back as duplicate.
     */
    data object Retry : BatchResult
}

/**
 * Sends a batch of events to the API (#33), each with its
 * [PendingPickupEventEntity.driverId] as stored, not the current session's user.
 */
fun interface PickupEventUploader {
    suspend fun upload(events: List<PendingPickupEventEntity>): BatchResult
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

    private val lock = Mutex()

    /**
     * Uploads the signed-in user's pending events, oldest first, in batches of
     * [MAX_BATCH]. Another user's events wait until that user signs in again.
     * Stops at the first [BatchResult.Retry], since the next batch would most
     * likely fail the same way. Runs one at a time, so a tap and a pull don't
     * send the same event twice. Returns how many of this user's events are
     * still pending.
     */
    suspend fun uploadPending(): Int = lock.withLock {
        val driverId = currentUserId() ?: return 0
        for (batch in dao.pending(driverId).chunked(MAX_BATCH)) {
            when (val result = uploader.upload(batch)) {
                BatchResult.Retry -> break

                is BatchResult.Answered -> for (event in batch) {
                    val key = event.idempotencyKey
                    when (val outcome = result.byKey[key]) {
                        UploadResult.Synced -> dao.markSynced(key, clock.instant())

                        // Terminal: retrying can never succeed, so it is shown to
                        // the driver instead, and the events behind it still go.
                        is UploadResult.Rejected -> dao.markConflict(key, outcome.code)

                        null -> Unit
                    }
                }
            }
        }
        dao.countPending(driverId)
    }

    companion object {
        /**
         * The server's limit per request. 50 events are about 13 KB, well
         * under its 32 KB limit, so a 413 can't happen.
         */
        const val MAX_BATCH = 50
    }
}
