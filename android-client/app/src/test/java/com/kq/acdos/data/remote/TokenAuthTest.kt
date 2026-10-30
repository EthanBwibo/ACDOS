package com.kq.acdos.data.remote

import com.kq.acdos.auth.AccessTokenProvider
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import retrofit2.create

/**
 * The bearer header and the 401 refresh-and-retry-once rule, against a real
 * local HTTP server. runBlocking, not runTest: OkHttp runs on its own threads.
 */
class TokenAuthTest {
    /** [current] is the session's token; a refresh replaces it with [refreshTo]. */
    private class FakeTokens(
        @Volatile var current: String?,
        private val refreshTo: String? = null,
        private val refreshDelayMs: Long = 0
    ) : AccessTokenProvider {
        val refreshCalls = AtomicInteger()

        override suspend fun accessToken() = current

        override suspend fun refreshAccessToken(): String? {
            refreshCalls.incrementAndGet()
            delay(refreshDelayMs)
            if (refreshTo != null) current = refreshTo
            return refreshTo
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

    private fun api(tokens: AccessTokenProvider): MeApi =
        ApiClient.retrofit(server.url("/").toString(), ApiClient.okHttp(tokens)).create()

    private fun respond(code: Int) =
        MockResponse.Builder().code(code).body("""{"pickup": null}""").build()

    /** Answers 200 only to [validToken], 401 to anything else. */
    private fun acceptOnly(validToken: String, onRequest: (RecordedRequest) -> Unit = {}) {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                onRequest(request)
                val ok = request.headers["Authorization"] == "Bearer $validToken"
                return respond(if (ok) 200 else 401)
            }
        }
    }

    @Test
    fun request_carriesBearerTokenAndNoApikey() = runBlocking {
        server.enqueue(respond(200))

        api(FakeTokens("t1")).crewPickup()

        val sent = server.takeRequest()
        assertEquals("Bearer t1", sent.headers["Authorization"])
        assertNull(sent.headers["apikey"])
    }

    @Test
    fun signedOut_sendsNoAuthorizationHeader() = runBlocking {
        server.enqueue(respond(401))

        api(FakeTokens(null)).crewPickup()

        assertNull(server.takeRequest().headers["Authorization"])
    }

    @Test
    fun unauthorized_refreshesOnceAndRetriesWithTheNewToken() = runBlocking {
        val tokens = FakeTokens("old", refreshTo = "new")
        acceptOnly("new")

        val response = api(tokens).crewPickup()

        assertEquals(200, response.code())
        assertEquals(1, tokens.refreshCalls.get())
        assertEquals("Bearer old", server.takeRequest().headers["Authorization"])
        assertEquals("Bearer new", server.takeRequest().headers["Authorization"])
    }

    @Test
    fun unauthorizedAgainAfterTheRetry_returns401WithoutASecondRefresh() = runBlocking {
        val tokens = FakeTokens("old", refreshTo = "new")
        acceptOnly("never")

        val response = api(tokens).crewPickup()

        assertEquals(401, response.code())
        assertEquals(1, tokens.refreshCalls.get())
        assertEquals(2, server.requestCount)
    }

    @Test
    fun concurrentUnauthorized_refreshOnce() = runBlocking {
        // The refresh is slow, so all four requests are waiting on it at once.
        val tokens = FakeTokens("old", refreshTo = "new", refreshDelayMs = 300)
        acceptOnly("new")
        val api = api(tokens)

        val codes = List(4) { async(Dispatchers.IO) { api.crewPickup().code() } }.awaitAll()

        assertEquals(listOf(200, 200, 200, 200), codes)
        assertEquals(1, tokens.refreshCalls.get())
    }

    @Test
    fun tokenChangedSinceThe401_retriesWithItWithoutRefreshing() = runBlocking {
        val tokens = FakeTokens("old", refreshTo = "refreshed")
        // Another part of the app refreshes while this request is in flight.
        acceptOnly("new") {
            if (it.headers["Authorization"] == "Bearer old") tokens.current = "new"
        }

        val response = api(tokens).crewPickup()

        assertEquals(200, response.code())
        assertEquals(0, tokens.refreshCalls.get())
    }

    @Test
    fun failedRefresh_returns401AndKeepsTheSession() = runBlocking {
        val tokens = FakeTokens("old", refreshTo = null)
        acceptOnly("new")

        val response = api(tokens).crewPickup()

        assertEquals(401, response.code())
        assertEquals(1, server.requestCount)
        // Nothing cleared the token: only supabase-kt ends a session.
        assertEquals("old", tokens.current)
    }

    @Test
    fun forbidden_reachesTheCallerWithoutARefresh() = runBlocking {
        val tokens = FakeTokens("driver-token", refreshTo = "new")
        server.enqueue(respond(403))

        val response = api(tokens).crewPickup()

        assertEquals(403, response.code())
        assertEquals(0, tokens.refreshCalls.get())
        assertEquals(1, server.requestCount)
    }
}
