package com.kq.acdos.ui.dispatcher

import com.kq.acdos.R
import com.kq.acdos.data.PickupEntryRepository
import com.kq.acdos.data.remote.CrewHomeDto
import com.kq.acdos.data.remote.CrewListItemDto
import com.kq.acdos.data.remote.CrewListPageDto
import com.kq.acdos.data.remote.DispatcherApi
import com.kq.acdos.data.remote.DispatcherPickupDto
import com.kq.acdos.data.remote.LatLonDto
import com.kq.acdos.data.remote.NearestZoneDto
import com.kq.acdos.data.remote.PickupReportTimeUpdateDto
import com.kq.acdos.data.remote.PickupRequestCreateDto
import com.kq.acdos.data.remote.PickupRequestStatusDto
import com.kq.acdos.data.remote.PickupRequestTypeDto
import com.kq.acdos.data.remote.VehicleStatusUpdateDto
import java.io.IOException
import java.time.Instant
import java.time.LocalDate
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Response

private val REPORT: Instant = Instant.parse("2026-11-21T02:30:00Z") // 05:30 Nairobi
private val WESTLANDS_HOME = LatLonDto(-1.2676, 36.8108)
private val AMINA = CrewListItemDto(
    "c1",
    "KQ1001",
    "Amina Otieno",
    "cabin_crew",
    WESTLANDS_HOME,
    "Westlands"
)
private val BRIAN = CrewListItemDto(
    "c2",
    "KQ1002",
    "Brian Kamau",
    "pilot",
    LatLonDto(-1.2921, 36.8219),
    "Nairobi CBD"
)
private val NEAR = LatLonDto(-1.2700, 36.8100)
private val FAR = LatLonDto(-1.0333, 37.0693)
private val IN_RANGE = NearestZoneDto("Westlands", 0.3, withinPickupZones = true)
private val TOO_FAR = NearestZoneDto("Ruiru", 14.2, withinPickupZones = false)

private fun errorBody(code: String, detail: String) =
    """{"code":"$code","detail":"$detail"}""".toResponseBody("application/json".toMediaType())

/** The Crew list, Add pickup and Set home (#253), against the contract in docs/openapi.json. */
@OptIn(ExperimentalCoroutinesApi::class)
class PickupEntryViewModelTest {
    private val scheduler = StandardTestDispatcher()

    private class FakeApi : DispatcherApi {
        /** Each crew call: its query and cursor. */
        val crewCalls = mutableListOf<Pair<String?, String?>>()
        val nearestCalls = mutableListOf<Pair<Double, Double>>()
        val added = mutableListOf<Pair<String, PickupRequestCreateDto>>()
        val homes = mutableListOf<Pair<String, LatLonDto>>()

        /** The crew list as two pages: AMINA, then BRIAN. */
        var pages = true

        /** The next add fails this way: an IOException, or an HTTP status and error code. */
        var addFails: Any? = null

        /** When set, the next nearest-zone answer waits for this. */
        var nearestGate: CompletableDeferred<Unit>? = null

        override suspend fun crew(
            query: String?,
            cursor: String?,
            limit: Int?
        ): Response<CrewListPageDto> {
            crewCalls += query to cursor
            val page = when {
                !pages -> CrewListPageDto(listOf(AMINA, BRIAN), null)
                cursor == null -> CrewListPageDto(listOf(AMINA), "page-2")
                else -> CrewListPageDto(listOf(BRIAN), null)
            }
            return Response.success(page)
        }

        override suspend fun nearestZone(lat: Double, lon: Double): Response<NearestZoneDto> {
            nearestCalls += lat to lon
            nearestGate?.also { nearestGate = null }?.await()
            return Response.success(if (lat == FAR.lat) TOO_FAR else IN_RANGE)
        }

        override suspend fun addPickup(
            idempotencyKey: String,
            body: PickupRequestCreateDto
        ): Response<DispatcherPickupDto> {
            added += idempotencyKey to body
            when (val fail = addFails.also { addFails = null }) {
                is IOException -> throw fail

                is Pair<*, *> -> return Response.error(
                    fail.first as Int,
                    errorBody(fail.second as String, "refused")
                )
            }
            val pickup = DispatcherPickupDto(
                "p1",
                "Amina Otieno",
                "Westlands",
                -1.27,
                36.81,
                body.reportTime,
                PickupRequestStatusDto.PENDING,
                needsAck = false,
                acknowledgedAt = null
            )
            return Response.success(201, pickup)
        }

        override suspend fun setHome(crewMemberId: String, body: LatLonDto): Response<CrewHomeDto> {
            homes += crewMemberId to body
            return Response.success(CrewHomeDto(crewMemberId, body, "Westlands", 0.3))
        }

        override suspend fun pickups(date: LocalDate?, cursor: String?, limit: Int?) =
            error("not used here")

        override suspend fun vehicles(cursor: String?, limit: Int?) = error("not used here")

        override suspend fun routes(date: LocalDate?, cursor: String?, limit: Int?) =
            error("not used here")

        override suspend fun setReportTime(pickupId: String, update: PickupReportTimeUpdateDto) =
            error("not used here")

        override suspend fun setVehicleStatus(vehicleId: String, update: VehicleStatusUpdateDto) =
            error("not used here")

        override suspend fun importRoster(
            file: MultipartBody.Part,
            dryRun: Boolean,
            idempotencyKey: String?
        ) = error("not used here")
    }

    private val api = FakeApi()
    private var keys = 0
    private lateinit var viewModel: PickupEntryViewModel

    private val form get() = viewModel.addPickup.value

    @Before
    fun setUp() {
        Dispatchers.setMain(scheduler)
        viewModel = PickupEntryViewModel(PickupEntryRepository(api), { "key-${++keys}" })
    }

    @After
    fun tearDown() = Dispatchers.resetMain()

    private fun filledIn(crew: CrewListItemDto = AMINA) {
        viewModel.chooseCrew(crew)
        viewModel.setReportTime(REPORT)
    }

    // The Crew list.

    @Test
    fun theCrewList_loadsTwentyAtATime_andLoadsMore() = runTest(scheduler) {
        viewModel.loadCrewList()
        advanceUntilIdle()
        assertEquals(listOf("Amina Otieno"), viewModel.crewList.value.items.map { it.name })
        assertEquals("page-2", viewModel.crewList.value.nextCursor)

        viewModel.loadMoreCrew()
        advanceUntilIdle()

        val names = viewModel.crewList.value.items.map { it.name }
        assertEquals(listOf("Amina Otieno", "Brian Kamau"), names)
        assertNull(viewModel.crewList.value.nextCursor)
        assertEquals(listOf(null to null, null to "page-2"), api.crewCalls)
    }

    @Test
    fun searchingTheCrewList_waitsForAPauseInTyping() = runTest(scheduler) {
        viewModel.searchCrewList("am")
        viewModel.searchCrewList("amin")
        advanceTimeBy(PickupEntryViewModel.SEARCH_DELAY_MS - 1)
        assertEquals(emptyList<Pair<String?, String?>>(), api.crewCalls)

        advanceUntilIdle()

        assertEquals(listOf<Pair<String?, String?>>("amin" to null), api.crewCalls)
    }

    // Add pickup.

    @Test
    fun theFormSearchesOnceAfterAPause_andNotForOneLetter() = runTest(scheduler) {
        api.pages = false
        viewModel.search("a")
        advanceUntilIdle()
        assertEquals("one letter", 0, api.crewCalls.size)

        viewModel.search("am")
        viewModel.search("ami")
        advanceUntilIdle()

        assertEquals(listOf<Pair<String?, String?>>("ami" to null), api.crewCalls)
        assertEquals(listOf("Amina Otieno", "Brian Kamau"), form.results.map { it.name })
    }

    @Test
    fun fromHome_sendsNoLocation() = runTest(scheduler) {
        filledIn()
        assertTrue(form.canSave)

        viewModel.save()
        advanceUntilIdle()

        val sent = api.added.single().second
        assertEquals(PickupRequestCreateDto("c1", REPORT, PickupRequestTypeDto.ROSTERED), sent)
        assertEquals("p1", form.added?.id)
        assertFalse("done", form.canSave)
    }

    @Test
    fun aStandbyFromAPin_sendsThePin() = runTest(scheduler) {
        filledIn()
        viewModel.setType(PickupRequestTypeDto.STANDBY)
        viewModel.startPin()
        viewModel.placePin(NEAR)
        advanceUntilIdle()
        viewModel.usePin()

        viewModel.save()
        advanceUntilIdle()

        val sent = api.added.single().second
        assertEquals(PickupRequestTypeDto.STANDBY, sent.requestType)
        assertEquals(NEAR, sent.pickupLocation)
    }

    @Test
    fun theFormNeedsACrewMemberAndATime() {
        viewModel.chooseCrew(BRIAN)
        assertFalse("no time yet", form.canSave)

        viewModel.setReportTime(REPORT)
        assertTrue(form.canSave)

        viewModel.chooseCrew(null)
        assertFalse("no crew member", form.canSave)
    }

    @Test
    fun aRetryAfterNoAnswer_sendsTheSameKey_andAChangeGetsANewOne() = runTest(scheduler) {
        filledIn()
        api.addFails = IOException("no signal")
        viewModel.save()
        advanceUntilIdle()
        assertEquals(R.string.dispatch_offline, form.failure?.text)

        // Still no answer on the retry, so the form stays open.
        api.addFails = IOException("no signal")
        viewModel.save()
        advanceUntilIdle()
        assertEquals(listOf("key-1", "key-1"), api.added.map { it.first })

        viewModel.setType(PickupRequestTypeDto.STANDBY)
        viewModel.save()
        advanceUntilIdle()
        assertEquals("key-2", api.added.last().first)
    }

    @Test
    fun eachRefusal_isInTheImportsWords() = runTest(scheduler) {
        val reasons = mapOf(
            "outside_pickup_zones" to R.string.roster_reason_outside_zones,
            "report_time_past" to R.string.roster_reason_report_time_past,
            "duplicate_pickup" to R.string.roster_reason_duplicate
        )
        for ((code, words) in reasons) {
            viewModel.startAddPickup()
            filledIn()
            api.addFails = 422 to code

            viewModel.save()
            advanceUntilIdle()

            assertEquals(code, words, form.failure?.text)
            assertNull(form.added)
            assertTrue("can try again after fixing it", form.canSave)
        }
    }

    @Test
    fun aCrewOrDriverAccount_isToldItIsNotAllowed() = runTest(scheduler) {
        filledIn()
        api.addFails = 403 to "forbidden"

        viewModel.save()
        advanceUntilIdle()

        assertEquals(R.string.dispatch_not_allowed, form.failure?.text)
    }

    // The map pin.

    @Test
    fun eachPinDrop_asksOnce_andOnlyAPinWithinTheZonesCanBeUsed() = runTest(scheduler) {
        viewModel.startPin()
        viewModel.placePin(FAR)
        advanceUntilIdle()

        assertEquals(TOO_FAR, viewModel.pin.value.nearest)
        assertFalse(viewModel.pin.value.usable)
        filledIn()
        viewModel.usePin()
        assertEquals("not kept", PickupPlace.Home, form.place)

        viewModel.placePin(NEAR)
        advanceUntilIdle()

        assertTrue(viewModel.pin.value.usable)
        assertEquals(2, api.nearestCalls.size)
    }

    @Test
    fun anOlderAnswer_neverShowsForANewerPin() = runTest(scheduler) {
        val gate = CompletableDeferred<Unit>()
        api.nearestGate = gate
        viewModel.placePin(NEAR)
        advanceUntilIdle()
        assertTrue("still checking", viewModel.pin.value.checking)

        viewModel.placePin(FAR)
        gate.complete(Unit)
        advanceUntilIdle()

        assertEquals(FAR, viewModel.pin.value.point)
        assertEquals(TOO_FAR, viewModel.pin.value.nearest)
    }

    // Set home.

    @Test
    fun setHome_movesTheirHome_andTheListAndDetailShowIt() = runTest(scheduler) {
        viewModel.loadCrewList()
        advanceUntilIdle()
        viewModel.loadMoreCrew()
        advanceUntilIdle()
        viewModel.openCrew(BRIAN)
        viewModel.startPin()
        viewModel.placePin(NEAR)
        advanceUntilIdle()

        viewModel.saveHome()
        advanceUntilIdle()

        assertEquals(listOf("c2" to NEAR), api.homes)
        assertEquals("Westlands", viewModel.setHome.value.saved?.zoneLabel)
        assertEquals("Westlands", viewModel.crewDetail.value?.homeZoneLabel)
        val listed = viewModel.crewList.value.items.first { it.id == "c2" }
        assertEquals(NEAR, listed.home)
    }

    @Test
    fun setHome_beyondTenKilometres_sendsNothing() = runTest(scheduler) {
        viewModel.openCrew(BRIAN)
        viewModel.placePin(FAR)
        advanceUntilIdle()

        viewModel.saveHome()
        advanceUntilIdle()

        assertEquals(emptyList<Pair<String, LatLonDto>>(), api.homes)
    }
}
