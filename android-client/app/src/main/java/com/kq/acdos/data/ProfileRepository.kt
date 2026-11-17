package com.kq.acdos.data

import com.kq.acdos.auth.AppRole
import com.kq.acdos.data.local.MyProfileDao
import com.kq.acdos.data.local.MyProfileEntity
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.MeApi
import com.kq.acdos.data.remote.apiCall
import java.time.Instant
import kotlinx.coroutines.flow.Flow
import retrofit2.Response

/**
 * Keeps the Room copy of the Profile screen's details (#231) in step with
 * GET /crew/me or GET /drivers/me. A failed refresh leaves the copy as it
 * was, so the screen still opens with no signal.
 */
class ProfileRepository(
    private val api: MeApi,
    private val dao: MyProfileDao,
    private val clock: () -> Instant = Instant::now
) {
    val profile: Flow<MyProfileEntity?> = dao.observe()

    suspend fun refresh(role: AppRole): RefreshResult = when (role) {
        AppRole.CREW -> fetch({ api.crewMe() }) {
            MyProfileEntity(crewRole = it.crewRole, homeZone = it.homeZone, fetchedAt = clock())
        }

        AppRole.DRIVER -> fetch({ api.driverMe() }) {
            val van = it.vehicle
            MyProfileEntity(
                vehiclePlate = van?.plateNumber,
                vehicleSeats = van?.capacity,
                vehicleStatus = van?.status?.name?.lowercase(),
                fetchedAt = clock()
            )
        }

        // The dispatcher has no Profile screen.
        AppRole.DISPATCHER -> RefreshResult.NOT_ALLOWED
    }

    private suspend fun <T : Any> fetch(
        call: suspend () -> Response<T>,
        toEntity: (T) -> MyProfileEntity
    ): RefreshResult = when (val result = apiCall(call)) {
        is ApiResult.Success -> {
            dao.save(toEntity(result.body))
            RefreshResult.UPDATED
        }

        is ApiResult.NetworkError -> RefreshResult.OFFLINE

        is ApiResult.Error -> result.asRefreshResult()
    }
}
