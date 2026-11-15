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

private fun message(
    id: String,
    readAt: Instant? = null,
    sentAt: Instant = SENT_AT,
    replies: List<MessageReplyDto> = emptyList()
) = CrewMessageDto(id, "crew-$id", "Crew $id", "late", "Late", sentAt, readAt, replies)

private fun minutes(n: Long): Instant = SENT_AT.plusSeconds(n * 60)

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

        var failPresets = false

        override suspend fun presets(): Response<PresetMessageListDto> {
            if (failPresets) throw IOException("no signal")
            val presets = listOf(PresetMessageDto("noted", "Noted"))
            return Response.success(PresetMessageListDto(presets))
        }

        override suspend fun send(idempotencyKey: String, body: CrewMessageCreateDto) =
            error("the dispatcher sends no messages")

        var failInbox = false
        var inbox = listOf(message("m1"), message("m2", SENT_AT))

        override suspend fun messages(cursor: String?, limit: Int?): Response<CrewMessagePageDto> {
            if (failInbox) throw IOException("no signal")
            return Response.success(CrewMessagePageDto(inbox, null))
        }

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

    private fun open() {
        viewModel = InboxViewModel(MessagesRepository(api, db.crewDao()), { "key-${++keys}" })
    }

    @Before
    fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        db = inMemoryDatabase()
        open()
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
        val reply = MessageReplyDto("r0", "noted", "Noted", minutes(1))
        api.inbox = listOf(message("m1", replies = listOf(reply)))
        open()

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
        // The reply moved the selection on to m2; pick m1 again.
        viewModel.select("m1")

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
    fun `a failed load says so and keeps the list, until a load works`() {
        api.failInbox = true
        viewModel.load()

        assertEquals(true, viewModel.loadFailed.value)
        assertEquals(false, viewModel.loading.value)
        assertEquals(2, viewModel.messages.value?.size)

        api.failInbox = false
        viewModel.load()

        assertEquals(false, viewModel.loadFailed.value)
    }

    /** m1 and m2 have no reply yet, m3 (the newest) has one. */
    private fun openWithThree() {
        val answered = MessageReplyDto("r0", "noted", "Noted", minutes(3))
        api.inbox = listOf(
            message("m3", sentAt = minutes(2), replies = listOf(answered)),
            message("m2", sentAt = minutes(1)),
            message("m1", sentAt = minutes(0))
        )
        open()
    }

    @Test
    fun `the newest unanswered message is selected by default`() {
        openWithThree()

        assertEquals("m2", viewModel.selected.value)
    }

    @Test
    fun `the default selection doesn't mark the message read`() {
        openWithThree()

        assertEquals(emptyList<String>(), api.read)
    }

    @Test
    fun `nothing is selected when every message is answered`() {
        val reply = MessageReplyDto("r0", "noted", "Noted", minutes(1))
        api.inbox = listOf(message("m1", replies = listOf(reply)))
        open()

        assertNull(viewModel.selected.value)
    }

    @Test
    fun `tapping another message switches the selection`() {
        openWithThree()

        viewModel.select("m1")

        assertEquals("m1", viewModel.selected.value)
    }

    @Test
    fun `a refresh keeps the message the dispatcher picked`() {
        openWithThree()
        viewModel.select("m3")

        viewModel.load()

        assertEquals("m3", viewModel.selected.value)
    }

    @Test
    fun `after a reply the next unanswered message is selected`() {
        openWithThree()
        api.answer = { MessageReplyDto("r1", "noted", "Noted", minutes(5)) }

        viewModel.reply("noted")

        assertEquals(listOf("m2" to "noted"), api.replied)
        assertEquals("m1", viewModel.selected.value)
    }

    @Test
    fun `after the last unanswered message is replied to, nothing is selected`() {
        api.inbox = listOf(message("m1"))
        open()

        viewModel.reply("noted")

        assertNull(viewModel.selected.value)
    }

    @Test
    fun `replies that fail to load say so, and Retry loads them`() {
        api.failPresets = true
        open()

        assertEquals(true, viewModel.presetsFailed.value)

        api.failPresets = false
        viewModel.loadPresets()

        assertEquals(false, viewModel.presetsFailed.value)
        assertEquals(listOf("noted"), viewModel.replyPresets.value.map { it.code })
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
