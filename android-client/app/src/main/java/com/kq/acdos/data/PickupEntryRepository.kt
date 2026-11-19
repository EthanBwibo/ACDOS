package com.kq.acdos.data

import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.CrewHomeDto
import com.kq.acdos.data.remote.CrewListPageDto
import com.kq.acdos.data.remote.DispatcherApi
import com.kq.acdos.data.remote.DispatcherPickupDto
import com.kq.acdos.data.remote.LatLonDto
import com.kq.acdos.data.remote.NearestZoneDto
import com.kq.acdos.data.remote.PickupRequestCreateDto
import com.kq.acdos.data.remote.apiCall

/**
 * The Crew list, Add pickup and Set home (#253). Online only, like the rest of the
 * dispatcher's app. The server checks every write the way the roster import does,
 * so both paths refuse the same things for the same reasons.
 */
class PickupEntryRepository(private val api: DispatcherApi) {
    /** One page of crew in name order; [query] matches a name or staff number. */
    suspend fun crew(query: String?, cursor: String? = null): ApiResult<CrewListPageDto> =
        apiCall { api.crew(query?.takeIf { it.isNotBlank() }, cursor, PAGE_SIZE) }

    /** Once per pin placement, never while it moves. */
    suspend fun nearestZone(point: LatLonDto): ApiResult<NearestZoneDto> =
        apiCall { api.nearestZone(point.lat, point.lon) }

    /** [idempotencyKey] stays the same across retries of one Save, so it is added once. */
    suspend fun addPickup(
        pickup: PickupRequestCreateDto,
        idempotencyKey: String
    ): ApiResult<DispatcherPickupDto> = apiCall { api.addPickup(idempotencyKey, pickup) }

    /** Safe to retry: setting the same home twice leaves it the same. */
    suspend fun setHome(crewMemberId: String, point: LatLonDto): ApiResult<CrewHomeDto> =
        apiCall { api.setHome(crewMemberId, point) }

    companion object {
        /** The server's default page, small enough for 2G. */
        const val PAGE_SIZE = 20
    }
}
