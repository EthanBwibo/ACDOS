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
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Keeps the Room copy of the crew member's next pickup in step with
 * GET /crew/me/pickup (#52). A failed refresh leaves the copy as it was, so
 * the Pickup tab still shows the last known pickup with no signal.
 *
 * The notice table mirrors the server: after each refresh it holds only the
 * pickup's latest unacknowledged change (#53), if there is one.
 */
class CrewPickupRepository(
    private val api: MeApi,
    private val dao: CrewDao,
    private val clock: () -> Instant = Instant::now
) {
    private val lock = Mutex()

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
                fetchedAt = clock()
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

private fun ScheduleChangeNoticeDto.toEntity(pickupRequestId: String) =
    ScheduleChangeNoticeEntity(
        id = id,
        pickupRequestId = pickupRequestId,
        reason = reason.name.lowercase(),
        previousPickupTime = previousPickupTime,
        newPickupTime = newPickupTime,
        issuedAt = issuedAt,
        acknowledgedAt = null
    )
