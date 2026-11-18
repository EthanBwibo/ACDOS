package com.kq.acdos.data

import com.kq.acdos.auth.AppRole
import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.MyProfileEntity
import com.kq.acdos.data.local.inMemoryDatabase
import com.kq.acdos.data.remote.CrewMeDto
import com.kq.acdos.data.remote.DriverMeDto
import com.kq.acdos.data.remote.DriverVehicleDto
import com.kq.acdos.data.remote.VehicleStatusDto
import java.io.IOException
import java.time.Instant
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import retrofit2.Response

/** What a refresh does to the Profile screen's cached details (#231). */
@RunWith(RobolectricTestRunner::class)
class ProfileRepositoryTest {
    private val t0 = Instant.parse("2026-11-17T04:00:00Z")
    private lateinit var db: AcdosDatabase
    private val api = FakeMeApi()
    private lateinit var repository: ProfileRepository
    private var email: String? = "grace@acdos.test"

    @Before
    fun setUp() {
        db = inMemoryDatabase()
        repository = ProfileRepository(api, db.myProfileDao(), { email }, clock = { t0 })
    }

    @After
    fun tearDown() = db.close()

    private suspend fun cached() = repository.profile.first()

    @Test
    fun crew_getTheirRoleAndHomeZone() = runTest {
        api.nextCrewMe = { Response.success(CrewMeDto("cabin_crew", "Westlands, Nairobi")) }

        assertEquals(RefreshResult.UPDATED, repository.refresh(AppRole.CREW))

        val expected =
            MyProfileEntity(
                crewRole = "cabin_crew",
                homeZone = "Westlands, Nairobi",
                fetchedAt = t0
            )
        assertEquals(expected, cached())
    }

    @Test
    fun theDispatcher_getsTheirEmailFromTheSession() = runTest {
        assertEquals(RefreshResult.UPDATED, repository.refresh(AppRole.DISPATCHER))

        assertEquals(MyProfileEntity(email = "grace@acdos.test", fetchedAt = t0), cached())
    }

    @Test
    fun theDispatcher_withNoSessionEmail_savesNothing() = runTest {
        email = null

        assertEquals(RefreshResult.FAILED, repository.refresh(AppRole.DISPATCHER))

        assertNull(cached())
    }

    @Test
    fun drivers_getTheirVan() = runTest {
        api.nextDriverMe = {
            Response.success(
                DriverMeDto(DriverVehicleDto("KDA 001A", 14, VehicleStatusDto.BROKEN_DOWN))
            )
        }

        assertEquals(RefreshResult.UPDATED, repository.refresh(AppRole.DRIVER))

        val van = cached()!!
        assertEquals("KDA 001A", van.vehiclePlate)
        assertEquals(14, van.vehicleSeats)
        assertEquals("broken_down", van.vehicleStatus)
    }

    @Test
    fun aDriverWithNoVan_isSavedAsLoadedWithNoVan() = runTest {
        api.nextDriverMe = { Response.success(DriverMeDto(null)) }

        repository.refresh(AppRole.DRIVER)

        val saved = cached()!!
        assertNull(saved.vehiclePlate)
        assertEquals(t0, saved.fetchedAt)
    }

    @Test
    fun noSignalOrAnError_keepsTheCopy() = runTest {
        api.nextCrewMe = { Response.success(CrewMeDto("pilot", "Kilimani")) }
        repository.refresh(AppRole.CREW)
        val before = cached()

        api.nextCrewMe = { throw IOException("no signal") }
        assertEquals(RefreshResult.OFFLINE, repository.refresh(AppRole.CREW))
        api.nextCrewMe = {
            val body = """{"code":"forbidden","detail":"x"}"""
            Response.error(403, body.toResponseBody("application/json".toMediaType()))
        }
        assertEquals(RefreshResult.NOT_ALLOWED, repository.refresh(AppRole.CREW))

        assertEquals(before, cached())
    }
}
