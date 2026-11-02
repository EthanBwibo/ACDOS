package com.kq.acdos.data.outbox

import com.kq.acdos.auth.AccessTokenProvider
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import com.kq.acdos.data.remote.ApiClient
import java.time.Instant
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import retrofit2.create

/** What goes over the wire to POST /drivers/me/pickup-events, and how answers are read. */
class ApiPickupEventUploaderTest {
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

    private fun uploader() = ApiPickupEventUploader(
        ApiClient.retrofit(server.url("/").toString(), ApiClient.okHttp(tokens)).create()
    )

    private fun reply(code: Int, body: String) = server.enqueue(
        MockResponse.Builder()
            .code(code)
            .addHeader("Content-Type", "application/json")
            .body(body)
            .build()
    )

    private val confirmed = PendingPickupEventEntity(
        idempotencyKey = "k1",
        driverId = "d1",
        routeNodeId = "n1",
        eventType = PickupEventType.PICKUP_CONFIRMED,
        exceptionType = null,
        confirmedAt = Instant.parse("2026-11-01T04:28:00Z")
    )
    private val noShow = confirmed.copy(
        idempotencyKey = "k2",
        routeNodeId = "n2",
        eventType = PickupEventType.EXCEPTION,
        exceptionType = PickupExceptionType.NO_SHOW
    )
    private val traffic = confirmed.copy(
        idempotencyKey = "k3",
        routeNodeId = "n3",
        eventType = PickupEventType.EXCEPTION,
        exceptionType = PickupExceptionType.TRAFFIC_DELAY
    )

    @Test
    fun batch_isSentAsTheContractSays() = runBlocking {
        reply(200, """{"results":[]}""")

        uploader().upload(listOf(confirmed, noShow))

        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/drivers/me/pickup-events", request.url.encodedPath)
        assertEquals(
            """{"events":[""" +
                """{"idempotency_key":"k1","route_node_id":"n1","driver_id":"d1",""" +
                """"event_type":"pickup_confirmed","occurred_at":"2026-11-01T04:28:00Z"},""" +
                """{"idempotency_key":"k2","route_node_id":"n2","driver_id":"d1",""" +
                """"event_type":"exception","exception_type":"no_show",""" +
                """"occurred_at":"2026-11-01T04:28:00Z"}]}""",
            request.body!!.utf8()
        )
    }

    @Test
    fun results_areMatchedByKeyNotByPosition() = runBlocking {
        reply(
            200,
            """{"results":[""" +
                """{"idempotency_key":"k3","status":"rejected","code":"already_confirmed",""" +
                """"detail":"x"},""" +
                """{"idempotency_key":"k1","status":"accepted","event_id":"e1"},""" +
                """{"idempotency_key":"k2","status":"duplicate","event_id":"e2"}]}"""
        )

        val result = uploader().upload(listOf(confirmed, noShow, traffic))

        assertEquals(
            BatchResult.Answered(
                mapOf(
                    "k1" to UploadResult.Synced,
                    "k2" to UploadResult.Synced,
                    "k3" to UploadResult.Rejected("already_confirmed")
                )
            ),
            result
        )
    }

    @Test
    fun serverErrorsAndNoAnswer_retryTheWholeBatch() = runBlocking {
        reply(503, """{"code":"unavailable","detail":"x"}""")
        assertEquals(BatchResult.Retry, uploader().upload(listOf(confirmed)))

        server.close()
        assertEquals(BatchResult.Retry, uploader().upload(listOf(confirmed)))
    }
}
