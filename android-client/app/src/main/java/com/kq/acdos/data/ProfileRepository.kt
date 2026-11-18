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
 * was, so the screen still opens with no signal. The dispatcher's (#249)
 * comes from the signed-in session, through [email], with no API call.
 */
class ProfileRepository(
    private val api: MeApi,
    private val dao: MyProfileDao,
    private val email: suspend () -> String? = { null },
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

        // Read from the session on the device, so it works with no signal too.
        AppRole.DISPATCHER -> email()?.let {
            dao.save(MyProfileEntity(email = it, fetchedAt = clock()))
            RefreshResult.UPDATED
        } ?: RefreshResult.FAILED
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
