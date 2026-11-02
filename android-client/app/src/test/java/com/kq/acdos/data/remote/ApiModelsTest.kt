package com.kq.acdos.data.remote

import com.kq.acdos.auth.AccessTokenProvider
import java.time.Instant
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import retrofit2.create

/** Paths, query parameters and JSON for the #51 and #52 endpoints. */
class ApiModelsTest {
    private val tokens = object : AccessTokenProvider {
        override suspend fun accessToken() = "t"

        override suspend fun refreshAccessToken(): String? = null
    }

    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() = server.close()

    private val retrofit by lazy {
        ApiClient.retrofit(server.url("/").toString(), ApiClient.okHttp(tokens))
    }

    private fun reply(json: String) =
        server.enqueue(MockResponse.Builder().code(200).body(json).build())

    @Test
    fun driverRoute_parsesStopsAndFractionalSeconds() = runBlocking {
        reply(
            """{"route":{"route_id":"r1","status":"active","vehicle_plate":"KDA 123A",
            "stops":[{"route_node_id":"n1","seq_order":1,"crew_name":"Test Crew",
            "zone_label":"Westlands, Nairobi","scheduled_pickup":"2026-10-30T06:50:34.037197Z",
            "eta":null,"lat":-1.2675,"lon":36.81202},
            {"route_node_id":"n2","seq_order":2,"crew_name":"Second Crew","zone_label":null,
            "scheduled_pickup":"2026-10-30T07:05:00Z","lat":-1.29,"lon":36.8}]}}"""
        )

        val route = retrofit.create<MeApi>().driverRoute().body()!!.route!!

        assertEquals("/drivers/me/route", server.takeRequest().url.encodedPath)
        assertEquals(RouteStatusDto.ACTIVE, route.status)
        assertEquals("KDA 123A", route.vehiclePlate)
        val first = route.stops[0]
        assertEquals("n1", first.routeNodeId)
        assertEquals("Westlands, Nairobi", first.zoneLabel)
        assertEquals(Instant.parse("2026-10-30T06:50:34.037197Z"), first.scheduledPickup)
        assertEquals(37_197_000, first.scheduledPickup.nano)
        assertNull(first.eta)
        assertEquals(36.81202, first.lon, 0.0)
        // eta absent rather than null, and no zone label.
        assertNull(route.stops[1].eta)
        assertNull(route.stops[1].zoneLabel)
    }

    @Test
    fun driverRoute_noActiveRoute() = runBlocking {
        reply("""{"route":null}""")

        assertNull(retrofit.create<MeApi>().driverRoute().body()!!.route)
    }

    @Test
    fun driverRoutes_passesCursorAndLimitAndReadsNextCursor() = runBlocking {
        val page = """{"items":[{"route_id":"r1","status":"completed","vehicle_plate":"KDA 123A",
            "first_pickup":"2026-10-29T03:10:00.5Z","stop_count":4,"total_distance_km":38.2}],
            "next_cursor":"abc"}"""
        reply(page)
        reply("""{"items":[],"next_cursor":null}""")
        val api = retrofit.create<MeApi>()

        val first = api.driverRoutes().body()!!
        val last = api.driverRoutes(cursor = "abc", limit = 50).body()!!

        // The first page sends neither parameter: the backend's defaults apply.
        val firstUrl = server.takeRequest().url
        assertEquals("/drivers/me/routes", firstUrl.encodedPath)
        assertNull(firstUrl.encodedQuery)
        val second = server.takeRequest().url
        assertEquals("abc", second.queryParameter("cursor"))
        assertEquals("50", second.queryParameter("limit"))
        assertEquals(RouteStatusDto.COMPLETED, first.items.single().status)
        assertEquals(4, first.items.single().stopCount)
        assertEquals("abc", first.nextCursor)
        assertNull(last.nextCursor)
    }

    @Test
    fun crewPickup_unplannedHasNoTimeOrPlate() = runBlocking {
        reply(
            """{"pickup":{"pickup_request_id":"p1","status":"pending",
            "report_time":"2026-10-30T09:00:00+03:00","scheduled_pickup":null,"eta":null,
            "vehicle_plate":null}}"""
        )

        val pickup = retrofit.create<MeApi>().crewPickup().body()!!.pickup!!

        assertEquals("/crew/me/pickup", server.takeRequest().url.encodedPath)
        assertEquals(PickupRequestStatusDto.PENDING, pickup.status)
        // An explicit offset is read too, not only "Z".
        assertEquals(Instant.parse("2026-10-30T06:00:00Z"), pickup.reportTime)
        assertNull(pickup.scheduledPickup)
        assertNull(pickup.vehiclePlate)
    }

    @Test
    fun crewPickup_nothingComingUp() = runBlocking {
        reply("""{"pickup":null}""")

        assertNull(retrofit.create<MeApi>().crewPickup().body()!!.pickup)
    }

    @Test
    fun createJob_sendsIdempotencyKeyAndSnakeCaseBody() = runBlocking {
        server.enqueue(MockResponse.Builder().code(202).body("""{"id":"job-1"}""").build())
        val body = OptimisationJobCreateDto(
            OptimizationTriggerTypeDto.FLIGHT_DELAY,
            pickupRequestIds = listOf("p1", "p2"),
            vehicleIds = listOf("v1")
        )

        val response = retrofit.create<OptimisationJobsApi>().createJob("key-1", body)

        assertEquals(202, response.code())
        assertEquals("job-1", response.body()!!.id)
        val sent = server.takeRequest()
        assertEquals("POST", sent.method)
        assertEquals("/optimisation-jobs", sent.url.encodedPath)
        assertEquals("key-1", sent.headers["Idempotency-Key"])
        val expected = """{"trigger_type":"flight_delay",""" +
            """"pickup_request_ids":["p1","p2"],"vehicle_ids":["v1"]}"""
        assertEquals(expected, sent.body!!.utf8())
    }

    @Test
    fun getJob_parsesACompletedPlan() = runBlocking {
        reply(
            """{"id":"job-1","status":"completed","error":null,
            "routes":[{"vehicle_id":"v1","total_distance_km":41.5,
            "planned_departure":"2026-10-30T03:05:00Z",
            "planned_arrival":"2026-10-30T04:20:00Z",
            "nodes":[{"pickup_request_id":"p1","seq_order":1,
            "estimated_arrival":"2026-10-30T03:40:00.123456Z"}]}],
            "late":[{"pickup_request_id":"p2","late_sec":420}],"unassigned":["p3"]}"""
        )

        val job = retrofit.create<OptimisationJobsApi>().getJob("job-1").body()!!

        assertEquals("/optimisation-jobs/job-1", server.takeRequest().url.encodedPath)
        assertEquals(OptimizationJobStatusDto.COMPLETED, job.status)
        assertEquals("p1", job.routes.single().nodes.single().pickupRequestId)
        assertEquals(Instant.parse("2026-10-30T03:05:00Z"), job.routes.single().plannedDeparture)
        assertEquals(420, job.late.single().lateSec)
        assertEquals(listOf("p3"), job.unassigned)
    }

    @Test
    fun getJob_queuedHasNoPlanYet() = runBlocking {
        reply("""{"id":"job-1","status":"queued"}""")

        val job = retrofit.create<OptimisationJobsApi>().getJob("job-1").body()!!

        assertEquals(OptimizationJobStatusDto.QUEUED, job.status)
        assertEquals(emptyList<PlannedRouteDto>(), job.routes)
    }
}
