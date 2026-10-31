package com.kq.acdos.data.remote

import com.kq.acdos.auth.AccessTokenProvider
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.create

/** How apiCall sorts responses, and how it reads the error envelope (#126). */
class ApiResultTest {
    private val refreshCalls = AtomicInteger()
    private val tokens = object : AccessTokenProvider {
        override suspend fun accessToken() = "t"

        override suspend fun refreshAccessToken(): String? {
            refreshCalls.incrementAndGet()
            return "new"
        }
    }

    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() = server.close()

    private fun retrofit() =
        ApiClient.retrofit(server.url("/").toString(), ApiClient.okHttp(tokens))

    private fun reply(code: Int, body: String, type: String = "application/json") = server.enqueue(
        MockResponse.Builder().code(code).addHeader("Content-Type", type).body(body).build()
    )

    private fun crewPickup() = runBlocking { apiCall { retrofit().create<MeApi>().crewPickup() } }

    private fun error(result: ApiResult<*>) = result as ApiResult.Error

    @Test
    fun success_carriesTheBody() {
        reply(200, """{"pickup": null}""")

        val result = crewPickup()

        assertEquals(ApiResult.Success(CrewPickupResponseDto(pickup = null)), result)
    }

    @Test
    fun errorBody_givesTheCodeDetailAndIds() {
        reply(
            409,
            """{"code":"departed_routes","detail":"already on the road",
            "pickup_request_ids":["p1","p2"]}"""
        )

        val result = error(crewPickup())

        assertEquals(409, result.status)
        assertEquals(ErrorCode.DEPARTED_ROUTES, result.code)
        assertEquals("already on the road", result.body!!.detail)
        assertEquals(listOf("p1", "p2"), result.body!!.pickupRequestIds)
        assertEquals(emptyList<String>(), result.body!!.vehicleIds)
    }

    @Test
    fun unknownCode_isTheGenericErrorAndKeepsTheDetail() {
        reply(429, """{"code":"rate_limited","detail":"slow down"}""")

        val result = error(crewPickup())

        assertEquals(429, result.status)
        assertEquals(ErrorCode.UNKNOWN, result.code)
        assertEquals("slow down", result.body!!.detail)
    }

    @Test
    fun proxyHtml502_isTheGenericErrorWithItsStatus() {
        reply(502, "<html><body>Bad Gateway</body></html>", type = "text/html")

        val result = error(crewPickup())

        assertEquals(502, result.status)
        assertEquals(ErrorCode.UNKNOWN, result.code)
        assertNull(result.body)
    }

    @Test
    fun bodiesThatAreNotAnErrorBody_areTheGenericError() {
        val notErrorBodies = listOf(
            "",
            "[1, 2]",
            """{"detail":"no code"}""",
            """{"code":"forbidden"}""",
            """{"code":null,"detail":"null code"}""",
            """{"code":"forbidden","detail":"x","pickup_request_ids":null}""",
            """{"code":"forbidden","detail": """
        )
        for (body in notErrorBodies) {
            reply(500, body)

            val result = error(crewPickup())

            assertEquals(body, 500, result.status)
            assertEquals(body, ErrorCode.UNKNOWN, result.code)
            assertNull(body, result.body)
        }
    }

    @Test
    fun unreadableSuccessBody_isTheGenericErrorNotACrash() {
        reply(200, """{"pickup": {"status": "assigned"}}""")
        reply(200, """{"pickup": nope}""")

        val wrongShape = crewPickup()
        val malformed = crewPickup()

        assertEquals(ApiResult.Error(status = null, body = null), wrongShape)
        assertEquals(ApiResult.Error(status = null, body = null), malformed)
    }

    @Test
    fun successBodyCutOff_isANetworkError() {
        // EOF mid-body looks the same as a dropped connection, so it is retried.
        reply(200, """{"pickup": """)

        val result = crewPickup()

        assertTrue(result.toString(), result is ApiResult.NetworkError)
    }

    @Test
    fun noServer_isANetworkError() {
        val url = server.url("/").toString()
        server.close()

        val result = runBlocking {
            apiCall {
                ApiClient.retrofit(url, ApiClient.okHttp(tokens)).create<MeApi>().crewPickup()
            }
        }

        assertTrue(result.toString(), result is ApiResult.NetworkError)
    }

    @Test
    fun jobsForbidden_isNotAllowedWithoutARefresh() {
        reply(403, """{"code":"forbidden","detail":"dispatchers only"}""")
        val body =
            OptimisationJobCreateDto(OptimizationTriggerTypeDto.SCHEDULED, listOf("p"), listOf("v"))

        val result = runBlocking {
            apiCall { retrofit().create<OptimisationJobsApi>().createJob("key-1", body) }
        }

        assertEquals(ErrorCode.FORBIDDEN, error(result).code)
        assertEquals(0, refreshCalls.get())
        assertEquals(1, server.requestCount)
    }
}
