package com.kq.acdos.ui.dispatcher

import com.kq.acdos.R
import com.kq.acdos.data.MessagesRepository
import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.inMemoryDatabase
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.CrewMessageCreateDto
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.data.remote.CrewMessagePageDto
import com.kq.acdos.data.remote.CrewMessageReadDto
import com.kq.acdos.data.remote.MessageReplyCreateDto
import com.kq.acdos.data.remote.MessageReplyDto
import com.kq.acdos.data.remote.MessagesApi
import com.kq.acdos.data.remote.PresetMessageDto
import com.kq.acdos.data.remote.PresetMessageListDto
import java.io.IOException
import java.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import retrofit2.Response

private val SENT_AT: Instant = Instant.parse("2026-11-07T03:00:00Z")

private fun message(id: String, readAt: Instant? = null) =
    CrewMessageDto(id, "crew-$id", "Crew $id", "late", "Late", SENT_AT, readAt, emptyList())

/** Marking messages read and the preset replies. */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
class InboxViewModelTest {
    private lateinit var db: AcdosDatabase
    private val api = FakeApi()
    private lateinit var viewModel: InboxViewModel
    private var keys = 0

    private class FakeApi : MessagesApi {
        val read = mutableListOf<String>()
        val keys = mutableListOf<String>()
        val replied = mutableListOf<Pair<String, String>>()
        var answer: () -> MessageReplyDto = { MessageReplyDto("r1", "noted", "Noted", SENT_AT) }

        override suspend fun presets() =
            Response.success(PresetMessageListDto(listOf(PresetMessageDto("noted", "Noted"))))

        override suspend fun send(idempotencyKey: String, body: CrewMessageCreateDto) =
            error("the dispatcher sends no messages")

        override suspend fun messages(cursor: String?, limit: Int?) = Response.success(
            CrewMessagePageDto(listOf(message("m1"), message("m2", SENT_AT)), null)
        )

        override suspend fun markRead(messageId: String): Response<CrewMessageReadDto> {
            read += messageId
            return Response.success(CrewMessageReadDto(messageId, SENT_AT))
        }

        override suspend fun reply(
            messageId: String,
            idempotencyKey: String,
            body: MessageReplyCreateDto
        ): Response<MessageReplyDto> {
            keys += idempotencyKey
            val reply = answer()
            replied += messageId to body.presetCode
            return Response.success(reply)
        }
    }

    private fun inboxMessage(id: String) = viewModel.messages.value!!.first { it.id == id }

    @Before
    fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        db = inMemoryDatabase()
        val repository = MessagesRepository(api, db.crewDao())
        viewModel = InboxViewModel(repository, newKey = { "key-${++keys}" })
    }

    @After
    fun tearDown() {
        db.close()
        Dispatchers.resetMain()
    }

    @Test
    fun `the reply presets load with the inbox`() {
        assertEquals(listOf("noted"), viewModel.replyPresets.value.map { it.code })
    }

    @Test
    fun `opening an unread message marks it read`() {
        viewModel.select("m1")

        assertEquals(listOf("m1"), api.read)
        assertNotNull(inboxMessage("m1").readAt)
    }

    @Test
    fun `opening a message already read asks nothing`() {
        viewModel.select("m2")

        assertEquals(emptyList<String>(), api.read)
    }

    @Test
    fun `a reply needs a message to go to`() {
        viewModel.reply("noted")

        assertEquals(emptyList<Pair<String, String>>(), api.replied)
    }

    @Test
    fun `a reply goes to the open message and shows on it`() {
        viewModel.select("m1")

        viewModel.reply("noted")

        assertEquals(listOf("m1" to "noted"), api.replied)
        assertEquals(listOf("Noted"), inboxMessage("m1").replies.map { it.label })
        assertEquals(emptyList<MessageReplyDto>(), inboxMessage("m2").replies)
    }

    @Test
    fun `a retry after no signal sends the same key`() {
        viewModel.select("m1")
        api.answer = { throw IOException("no signal") }
        viewModel.reply("noted")
        api.answer = { MessageReplyDto("r1", "noted", "Noted", SENT_AT) }

        viewModel.reply("noted")

        assertEquals(listOf("key-1", "key-1"), api.keys)
    }

    @Test
    fun `a second reply after one is sent gets a new key`() {
        viewModel.select("m1")
        viewModel.reply("noted")
        api.answer = { MessageReplyDto("r2", "noted", "Noted", SENT_AT) }

        viewModel.reply("noted")

        assertEquals(listOf("key-1", "key-2"), api.keys)
        assertEquals(2, inboxMessage("m1").replies.size)
    }

    @Test
    fun `a failed reply changes nothing on screen`() {
        viewModel.select("m1")
        api.answer = { throw IOException("no signal") }

        viewModel.reply("noted")

        assertEquals(emptyList<MessageReplyDto>(), inboxMessage("m1").replies)
    }

    @Test
    fun `no message is open until one is tapped`() {
        assertNull(viewModel.selected.value)
    }

    @Test
    fun `each outcome has its own words`() {
        assertEquals(R.string.dispatch_reply_sent, replyMessage(ApiResult.Success(Unit)))
        assertEquals(
            R.string.dispatch_reply_offline,
            replyMessage(ApiResult.NetworkError(IOException("no signal")))
        )
    }
}
