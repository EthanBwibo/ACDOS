package com.kq.acdos.data.outbox

import com.kq.acdos.auth.AccessTokenProvider
import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupExceptionType
import com.kq.acdos.data.local.inMemoryDatabase
import com.kq.acdos.data.remote.ApiClient
import com.kq.acdos.data.remote.ErrorCode
import com.kq.acdos.data.remote.MeApi
import com.kq.acdos.data.remote.PickupEventBatchDto
import com.kq.acdos.data.remote.PickupEventInDto
import com.kq.acdos.data.remote.PickupEventOutcomeDto
import com.kq.acdos.data.remote.PickupEventResultDto
import com.kq.acdos.data.remote.PickupEventResultsDto
import com.kq.acdos.data.remote.PickupEventTypeDto
import java.io.File
import java.io.IOException
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import kotlin.random.Random
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import retrofit2.create

private const val DRIVER = "driver-1"
private const val SEED = 34
private const val STOPS = 100

// The other seeds, for the same checks over many different fault sequences.
private val SEEDS = 1..20

/** What happens to one upload request on the way. */
enum class Fault {
    /** It reaches the server and the answer comes back. */
    NONE,

    /** No signal: it never reaches the server. */
    NO_CONNECTION,

    /** A 503 from in front of the server: nothing applied. */
    SERVER_ERROR,

    /** The server applies it, then the connection drops before the answer arrives. */
    RESPONSE_LOST
}

/**
 * The backend's rules for an upload (app/events.py), only those this script can trigger: a
 * stored key with the same fields is a duplicate (with different fields, idempotency_key_reused),
 * and a second confirmation of a stop is already_confirmed. Everything else is accepted. Logs
 * every delivery that reached it, so the backend can replay them against Postgres.
 */
private class ServerDouble {
    val stored = LinkedHashMap<String, PickupEventInDto>()
    private val confirmed = mutableSetOf<String>()
    val received = mutableMapOf<String, Int>()
    val deliveries = JSONArray()

    private val batches = ApiClient.moshi.adapter(PickupEventBatchDto::class.java)
    private val results = ApiClient.moshi.adapter(PickupEventResultsDto::class.java)

    fun handle(body: String, fault: Fault): String {
        val events = batches.fromJson(body)!!.events
        val answers = events.map { answer(it) }
        deliveries.put(
            JSONObject()
                .put("fault", fault.name)
                .put("keys", JSONArray(events.map { it.idempotencyKey }))
                .put(
                    "answers",
                    JSONArray(answers.map { JSONArray(listOf(it.status.name, it.codeName())) })
                )
        )
        return results.toJson(PickupEventResultsDto(answers))
    }

    private fun answer(event: PickupEventInDto): PickupEventResultDto {
        val key = event.idempotencyKey
        received.merge(key, 1, Int::plus)
        val earlier = stored[key]
        return when {
            earlier == event -> result(key, PickupEventOutcomeDto.DUPLICATE)

            earlier != null -> rejected(key, ErrorCode.IDEMPOTENCY_KEY_REUSED)

            event.eventType == PickupEventTypeDto.PICKUP_CONFIRMED &&
                event.routeNodeId in confirmed -> rejected(key, ErrorCode.ALREADY_CONFIRMED)

            else -> {
                stored[key] = event
                if (event.eventType == PickupEventTypeDto.PICKUP_CONFIRMED) {
                    confirmed += event.routeNodeId
                }
                result(key, PickupEventOutcomeDto.ACCEPTED)
            }
        }
    }

    private fun result(key: String, status: PickupEventOutcomeDto) =
        PickupEventResultDto(key, status, eventId = "event-$key")

    private fun rejected(key: String, code: ErrorCode) =
        PickupEventResultDto(key, PickupEventOutcomeDto.REJECTED, code = code, detail = code.name)

    private fun PickupEventResultDto.codeName(): Any =
        if (status == PickupEventOutcomeDto.REJECTED) code.name.lowercase() else JSONObject.NULL
}

/**
 * The phone's network, as the last interceptor: each request draws a [Fault] from a seeded
 * random source, and gets through only to [server]. Off once [healed].
 */
private class FlakyNetwork(
    private val random: Random,
    private val server: ServerDouble
) : Interceptor {
    var healed = false
    val attempts = Fault.entries.associateWith { 0 }.toMutableMap()

    private fun draw(): Fault {
        val r = random.nextDouble()
        return when {
            healed || r < 0.5 -> Fault.NONE
            r < 0.7 -> Fault.NO_CONNECTION
            r < 0.8 -> Fault.SERVER_ERROR
            else -> Fault.RESPONSE_LOST
        }
    }

    override fun intercept(chain: Interceptor.Chain): Response {
        val fault = draw()
        attempts.merge(fault, 1, Int::plus)
        val request = chain.request()
        return when (fault) {
            Fault.NO_CONNECTION -> throw IOException("no connection")

            Fault.SERVER_ERROR -> respond(request, 503, """{"code":"x","detail":"unavailable"}""")

            Fault.NONE, Fault.RESPONSE_LOST -> {
                val body = Buffer().also { request.body!!.writeTo(it) }.readUtf8()
                val answer = server.handle(body, fault)
                if (fault == Fault.RESPONSE_LOST) throw IOException("connection reset")
                respond(request, 200, answer)
            }
        }
    }

    private fun respond(request: Request, code: Int, json: String) = Response.Builder()
        .request(request)
        .protocol(Protocol.HTTP_1_1)
        .code(code)
        .message(if (code == 200) "OK" else "Service Unavailable")
        .body(json.toResponseBody("application/json".toMediaType()))
        .build()
}

/** One second further on at every reading, so events keep the order they were recorded in. */
private class TickingClock(private var now: Instant) : Clock() {
    override fun instant(): Instant = now.also { now = now.plusSeconds(1) }

    override fun getZone(): ZoneId = ZoneOffset.UTC

    override fun withZone(zone: ZoneId?): Clock = this
}

/** One seeded run: what the phone and the server ended with. */
private class Run(
    val seed: Int,
    val recorded: List<PendingPickupEventEntity>,
    val server: ServerDouble,
    val network: FlakyNetwork,
    val secondTaps: Set<String>,
    val restarts: Int,
    val simultaneousUploads: Int,
    val pending: Int
) {
    val synced = recorded.filter { it.syncedAt != null }.map { it.idempotencyKey }.toSet()
    val refused = recorded.filter { it.conflict != null }
    val lost = recorded.map { it.idempotencyKey }.toSet() - server.stored.keys - secondTaps
    val redelivered = server.received.values.filter { it > 1 }
    val stopsConfirmedTwice = server.stored.values
        .filter { it.eventType == PickupEventTypeDto.PICKUP_CONFIRMED }
        .groupingBy { it.routeNodeId }
        .eachCount()
        .count { it.value > 1 }

    fun report(): JSONObject = JSONObject()
        .put("seed", seed)
        .put("recorded", recorded.size)
        .put("second_taps", secondTaps.size)
        .put("upload_attempts", JSONObject(network.attempts.mapKeys { it.key.name }))
        .put("deliveries", server.deliveries.length())
        .put("app_restarts", restarts)
        .put("simultaneous_uploads", simultaneousUploads)
        .put("stored", server.stored.size)
        .put("synced_on_phone", synced.size)
        .put("refused_on_phone", refused.size)
        .put("pending_on_phone", pending)
        .put("events_delivered_more_than_once", redelivered.size)
        .put("extra_deliveries", redelivered.sumOf { it - 1 })
        .put("lost", lost.size)
        .put("stops_confirmed_twice", stopsConfirmedTwice)
}

/**
 * #34: a driver's day of pickup events through a network that keeps failing, with the app's
 * own outbox, Room, uploader, Retrofit and OkHttp. Only the socket is replaced, by
 * [FlakyNetwork] and [ServerDouble].
 *
 * A seeded script of [STOPS] stops: per stop, maybe traffic delays, a vehicle issue, a no-show,
 * then usually a pickup, and sometimes a second tap of Crew on board. After every few events
 * the app tries to upload; now and then the app restarts (a new outbox over the same
 * database) or two uploads start together. At the end the network heals and the app uploads
 * until nothing is pending.
 *
 * Loss is an event the phone recorded that the server never stored, except the second taps,
 * which it must refuse as already_confirmed. Writes to build/partition/: deliveries.json (seed
 * [SEED]'s deliveries that reached the server, which the backend replays against Postgres),
 * report.json, and seeds.json for [SEEDS].
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class PartitionTest {
    private val tokens = object : AccessTokenProvider {
        override suspend fun accessToken() = "token"

        override suspend fun refreshAccessToken(): String? = null
    }

    private val out = File("build/partition").apply { mkdirs() }

    /** The script for one seed, on a fresh database. */
    private suspend fun run(seed: Int): Run {
        val db = inMemoryDatabase()
        try {
            return script(db, seed)
        } finally {
            db.close()
        }
    }

    private suspend fun script(db: AcdosDatabase, seed: Int): Run {
        val random = Random(seed)
        val server = ServerDouble()
        val network = FlakyNetwork(random, server)
        val client = ApiClient.okHttp(tokens).newBuilder().addInterceptor(network).build()
        val api = ApiClient.retrofit("http://partition.test/", client).create<MeApi>()
        val clock = TickingClock(Instant.parse("2026-11-10T03:00:00Z"))
        var keys = 0
        fun newOutbox() = PickupEventOutbox(
            db.pendingPickupEventDao(),
            ApiPickupEventUploader(api),
            currentUserId = { DRIVER },
            clock = clock,
            newKey = { "k%04d".format(++keys) }
        )

        var outbox = newOutbox()
        val secondTaps = mutableSetOf<String>()
        var restarts = 0
        var simultaneous = 0
        var sinceUpload = 0
        var nextUpload = 1 + random.nextInt(6)

        suspend fun maybeUpload() {
            if (++sinceUpload < nextUpload) return
            sinceUpload = 0
            nextUpload = 1 + random.nextInt(6)
            if (random.nextDouble() < 0.1) {
                restarts++
                outbox = newOutbox()
            }
            if (random.nextDouble() < 0.1) {
                // A tap and a reconnect at once: both finish before the script goes on.
                simultaneous++
                val running = outbox
                coroutineScope {
                    launch { running.uploadPending() }
                    launch { running.uploadPending() }
                }
            } else {
                outbox.uploadPending()
            }
        }

        for (stop in 1..STOPS) {
            val node = "node-%03d".format(stop)
            repeat(random.nextInt(3)) {
                outbox.recordException(node, PickupExceptionType.TRAFFIC_DELAY)
                maybeUpload()
            }
            if (random.nextDouble() < 0.1) {
                outbox.recordException(node, PickupExceptionType.VEHICLE_ISSUE)
                maybeUpload()
            }
            if (random.nextDouble() < 0.2) {
                outbox.recordException(node, PickupExceptionType.NO_SHOW)
                maybeUpload()
            }
            if (random.nextDouble() < 0.9) {
                outbox.recordConfirmation(node)
                maybeUpload()
                if (random.nextDouble() < 0.1) {
                    secondTaps += outbox.recordConfirmation(node)
                    maybeUpload()
                }
            }
        }

        network.healed = true
        var pending = outbox.uploadPending()
        repeat(5) { if (pending > 0) pending = outbox.uploadPending() }

        val recorded = db.pendingPickupEventDao().observeAll(DRIVER).first()
        return Run(seed, recorded, server, network, secondTaps, restarts, simultaneous, pending)
    }

    private fun assertNothingLostOrStoredTwice(run: Run) {
        val seed = "seed ${run.seed}"
        assertTrue("$seed: at least 200 events", run.recorded.size >= 200)
        assertEquals("$seed: nothing lost", emptySet<String>(), run.lost)
        assertEquals("$seed: nothing left pending", 0, run.pending)
        assertEquals("$seed: synced is stored", run.server.stored.keys, run.synced)
        assertEquals(
            "$seed: only the second taps are refused, each as already_confirmed",
            run.secondTaps.associateWith { ErrorCode.ALREADY_CONFIRMED.name.lowercase() },
            run.refused.associate { it.idempotencyKey to it.conflict }
        )
        assertEquals("$seed: no stop confirmed twice", 0, run.stopsConfirmedTwice)
    }

    @Test
    fun `200 events through random disconnects are stored once each and none are lost`() =
        runBlocking {
            val run = run(SEED)

            assertNothingLostOrStoredTwice(run)
            assertTrue("every fault happened", run.network.attempts.values.all { it > 0 })
            assertTrue("retries delivered events again", run.redelivered.isNotEmpty())

            val events = run.recorded.associate { event ->
                event.idempotencyKey to JSONObject()
                    .put("node", event.routeNodeId)
                    .put("event_type", event.eventType.dbValue)
                    .put("exception_type", event.exceptionType?.dbValue ?: JSONObject.NULL)
                    .put("occurred_at", event.confirmedAt.toString())
            }
            File(out, "deliveries.json").writeText(
                JSONObject()
                    .put("seed", SEED)
                    .put("driver", DRIVER)
                    .put("events", JSONObject(events))
                    .put("deliveries", run.server.deliveries)
                    .toString(1) + "\n"
            )
            File(out, "report.json").writeText(run.report().toString(2) + "\n")
        }

    @Test
    fun `the same holds for every seed`() = runBlocking {
        val runs = SEEDS.map { run(it) }

        runs.forEach(::assertNothingLostOrStoredTwice)
        File(out, "seeds.json").writeText(JSONArray(runs.map { it.report() }).toString(2) + "\n")
    }
}
