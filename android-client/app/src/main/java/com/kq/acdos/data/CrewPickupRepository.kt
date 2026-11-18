package com.kq.acdos.data

import com.kq.acdos.data.local.CrewDao
import com.kq.acdos.data.local.CrewPickupEntity
import com.kq.acdos.data.local.ScheduleChangeNoticeEntity
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.CrewPickupDto
import com.kq.acdos.data.remote.MeApi
import com.kq.acdos.data.remote.ScheduleChangeNoticeDto
import com.kq.acdos.data.remote.apiCall
import java.time.Instant
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Keeps the Room copy of the crew member's next pickup in step with
 * GET /crew/me/pickup (#52). A failed refresh leaves the copy as it was, so
 * the Pickup tab still shows the last known pickup with no signal.
 *
 * The notice table mirrors the server: after each refresh it holds only the
 * pickup's latest unacknowledged change (#53), if there is one.
 *
 * The driver's first name and number (#255) are kept in memory only, never in
 * Room: the number is only meant to exist around the pickup, and the server
 * decides when that is, so each refresh replaces it.
 */
class CrewPickupRepository(
    private val api: MeApi,
    private val dao: CrewDao,
    private val clock: () -> Instant = Instant::now
) {
    private val lock = Mutex()

    private val contact = MutableStateFlow<DriverContact?>(null)

    /** From the last refresh that answered; null with no pickup. */
    val driverContact: StateFlow<DriverContact?> = contact.asStateFlow()

    /**
     * Called when the Pickup tab starts and on a pull. [RefreshResult.NO_ROUTE]
     * here means no pickup coming up. Calls run one at a time.
     */
    suspend fun refresh(): RefreshResult = lock.withLock {
        when (val result = apiCall { api.crewPickup() }) {
            is ApiResult.Success -> save(result.body.pickup)
            is ApiResult.NetworkError -> RefreshResult.OFFLINE
            is ApiResult.Error -> result.asRefreshResult()
        }
    }

    private suspend fun save(pickup: CrewPickupDto?): RefreshResult {
        dao.deleteNotices()
        contact.value = pickup?.let {
            DriverContact(it.pickupRequestId, it.driverFirstName, it.driverPhone)
        }
        if (pickup == null) {
            dao.deletePickups()
            return RefreshResult.NO_ROUTE
        }
        pickup.notice?.let { dao.upsertNotices(listOf(it.toEntity(pickup.pickupRequestId))) }
        dao.savePickup(
            CrewPickupEntity(
                pickupRequestId = pickup.pickupRequestId,
                // The live ETA once there is one (#52), else the planned time.
                estimatedPickup = pickup.eta ?: pickup.scheduledPickup,
                reportTime = pickup.reportTime,
                plateNumber = pickup.vehiclePlate,
                fetchedAt = clock(),
                status = pickup.status.name.lowercase()
            )
        )
        return RefreshResult.UPDATED
    }

    /**
     * POST /crew/me/notices/{id}/acknowledge. On success the notice is marked
     * acknowledged, which hides it; on failure it stays to tap again.
     */
    suspend fun acknowledge(noticeId: String): RefreshResult = lock.withLock {
        when (val result = apiCall { api.acknowledgeNotice(noticeId) }) {
            is ApiResult.Success -> {
                dao.markAcknowledged(noticeId, result.body.acknowledgedAt)
                RefreshResult.UPDATED
            }

            is ApiResult.NetworkError -> RefreshResult.OFFLINE

            is ApiResult.Error -> result.asRefreshResult()
        }
    }
}

/** Who is driving the crew member's pickup, and their number while it can be called (#255). */
data class DriverContact(
    val pickupRequestId: String,
    val firstName: String?,
    /** Null outside the server's window: then there is no Call button. */
    val phone: String?
)

private fun ScheduleChangeNoticeDto.toEntity(pickupRequestId: String) = ScheduleChangeNoticeEntity(
    id = id,
    pickupRequestId = pickupRequestId,
    reason = reason.name.lowercase(),
    previousPickupTime = previousPickupTime,
    newPickupTime = newPickupTime,
    issuedAt = issuedAt,
    acknowledgedAt = null
)
