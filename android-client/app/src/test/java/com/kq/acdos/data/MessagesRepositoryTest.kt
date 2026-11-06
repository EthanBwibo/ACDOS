package com.kq.acdos.data

import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.PresetMessageEntity
import com.kq.acdos.data.local.inMemoryDatabase
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.CrewMessageCreateDto
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.data.remote.CrewMessagePageDto
import com.kq.acdos.data.remote.CrewMessageReadDto
import com.kq.acdos.data.remote.MessagesApi
import com.kq.acdos.data.remote.PresetMessageDto
import com.kq.acdos.data.remote.PresetMessageListDto
import java.io.IOException
import java.time.Instant
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import retrofit2.Response

/** Presets cached for the crew's Message tab, a send, and the dispatcher's inbox. */
@RunWith(RobolectricTestRunner::class)
class MessagesRepositoryTest {
    private lateinit var db: AcdosDatabase
    private val api = FakeMessagesApi()
    private lateinit var repository: MessagesRepository

    private class FakeMessagesApi : MessagesApi {
        var presets: suspend () -> Response<PresetMessageListDto> = { error("no answer set") }
        val sent = mutableListOf<Pair<String, CrewMessageCreateDto>>()
        var inbox = listOf<CrewMessageDto>()

        override suspend fun presets() = presets.invoke()

        override suspend fun send(idempotencyKey: String, body: CrewMessageCreateDto) =
            Response.success(message("m${sent.size}", body.presetCode)).also {
                sent += idempotencyKey to body
            }

        override suspend fun messages(cursor: String?, limit: Int?) =
            Response.success(CrewMessagePageDto(inbox, null))

        override suspend fun markRead(messageId: String) =
            Response.success(CrewMessageReadDto(messageId, Instant.EPOCH))
    }

    @Before
    fun setUp() {
        db = inMemoryDatabase()
        repository = MessagesRepository(api, db.crewDao())
    }

    @After
    fun tearDown() = db.close()

    @Test
    fun presets_areCached_andAFailedRefreshKeepsThem() = runTest {
        api.presets = {
            Response.success(PresetMessageListDto(listOf(PresetMessageDto("running_late", "Late"))))
        }
        repository.refreshPresets()
        val cached = listOf(PresetMessageEntity("running_late", "running_late", "Late"))
        assertEquals(cached, db.crewDao().observePresets().first())

        api.presets = { throw IOException("offline") }
        assertTrue(repository.refreshPresets() is ApiResult.NetworkError)

        assertEquals(cached, db.crewDao().observePresets().first())
    }

    @Test
    fun send_postsThePresetCodeWithTheKey() = runTest {
        val result = repository.send("running_late", "key-1")

        assertEquals("running_late", (result as ApiResult.Success).body.presetCode)
        assertEquals(listOf("key-1" to CrewMessageCreateDto("running_late")), api.sent)
    }

    @Test
    fun inbox_keepsTheServersNewestFirstOrder() = runTest {
        api.inbox = listOf(message("m2", "at_pickup_point"), message("m1", "running_late"))

        val inbox = (repository.inbox() as ApiResult.Success).body

        assertEquals(listOf("m2", "m1"), inbox.map { it.id })
    }

    private companion object {
        fun message(id: String, code: String) =
            CrewMessageDto(id, "c1", "Test Crew", code, code, Instant.EPOCH, null, emptyList())
    }
}
