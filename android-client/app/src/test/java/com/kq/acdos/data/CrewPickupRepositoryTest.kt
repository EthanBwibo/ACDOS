package com.kq.acdos.data

import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.CrewPickupEntity
import com.kq.acdos.data.local.inMemoryDatabase
import com.kq.acdos.data.remote.CrewPickupDto
import com.kq.acdos.data.remote.CrewPickupResponseDto
import com.kq.acdos.data.remote.PickupRequestStatusDto
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

/** What a refresh does to the cached crew pickup for each answer from GET /crew/me/pickup. */
@RunWith(RobolectricTestRunner::class)
class CrewPickupRepositoryTest {
    private val t0 = Instant.parse("2026-11-03T04:00:00Z")
    private lateinit var db: AcdosDatabase
    private val api = FakeMeApi()
    private lateinit var repository: CrewPickupRepository

    @Before
    fun setUp() {
        db = inMemoryDatabase()
        repository = CrewPickupRepository(api, db.crewDao(), clock = { t0 })
    }

    @After
    fun tearDown() = db.close()

    private fun pickup(eta: Instant?, plate: String? = "KDA 002T") = CrewPickupDto(
        pickupRequestId = "p1",
        status = PickupRequestStatusDto.ASSIGNED,
        reportTime = t0.plusSeconds(5400),
        scheduledPickup = t0.plusSeconds(1680),
        eta = eta,
        vehiclePlate = plate
    )

    private fun answer(pickup: CrewPickupDto?) {
        api.nextCrew = { Response.success(CrewPickupResponseDto(pickup)) }
    }

    private suspend fun cached() = db.crewDao().observePickup().first()

    @Test
    fun aPickup_isSavedWithTheScheduledTimeUntilThereIsAnEta() = runTest {
        answer(pickup(eta = null))

        assertEquals(RefreshResult.UPDATED, repository.refresh())

        assertEquals(
            CrewPickupEntity("p1", t0.plusSeconds(1680), t0.plusSeconds(5400), "KDA 002T", t0),
            cached()
        )

        answer(pickup(eta = t0.plusSeconds(1900)))
        repository.refresh()

        assertEquals(t0.plusSeconds(1900), cached()?.estimatedPickup)
    }

    @Test
    fun noPickup_clearsTheCache() = runTest {
        answer(pickup(eta = null))
        repository.refresh()
        answer(null)

        assertEquals(RefreshResult.NO_ROUTE, repository.refresh())

        assertNull(cached())
    }

    @Test
    fun failures_keepTheLastKnownPickup() = runTest {
        answer(pickup(eta = null))
        repository.refresh()
        val before = cached()

        api.nextCrew = { throw IOException("offline") }
        assertEquals(RefreshResult.OFFLINE, repository.refresh())

        val body = """{"code":"unauthorized","detail":"x"}"""
        api.nextCrew = {
            Response.error(401, body.toResponseBody("application/json".toMediaType()))
        }
        assertEquals(RefreshResult.SIGN_IN_AGAIN, repository.refresh())

        assertEquals(before, cached())
    }
}
