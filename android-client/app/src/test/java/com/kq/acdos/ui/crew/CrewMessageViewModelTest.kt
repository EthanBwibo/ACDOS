package com.kq.acdos.ui.crew

import com.kq.acdos.R
import com.kq.acdos.data.MessagesRepository
import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.inMemoryDatabase
import com.kq.acdos.data.remote.CrewMessageCreateDto
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.data.remote.CrewMessagePageDto
import com.kq.acdos.data.remote.CrewMessageReadDto
import com.kq.acdos.data.remote.MessageReplyCreateDto
import com.kq.acdos.data.remote.MessageReplyDto
import com.kq.acdos.data.remote.MessagesApi
import com.kq.acdos.data.remote.PresetMessageListDto
import java.io.IOException
import java.time.Instant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import retrofit2.Response

private fun message(
    id: String,
    readAt: Instant? = null,
    sentAt: Instant = Instant.EPOCH,
    replies: List<MessageReplyDto> = emptyList()
) = CrewMessageDto(
    id = id,
    crewMemberId = "crew-1",
    crewName = "A. Sample",
    presetCode = "running_late",
    label = "I am running late",
    sentAt = sentAt,
    readAt = readAt,
    replies = replies
)

/** The RECENT list on the Message tab. */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
class CrewMessageViewModelTest {
    private lateinit var db: AcdosDatabase
    private val api = FakeApi()
    private lateinit var viewModel: CrewMessageViewModel

    private class FakeApi : MessagesApi {
        var mine: () -> List<CrewMessageDto> = { emptyList() }
        var answer: () -> CrewMessageDto = { message("sent") }
        var askedFor: Int? = null

        override suspend fun presets() = Response.success(PresetMessageListDto(emptyList()))

        override suspend fun send(idempotencyKey: String, body: CrewMessageCreateDto) =
            Response.success(answer())

        override suspend fun messages(cursor: String?, limit: Int?): Response<CrewMessagePageDto> {
            askedFor = limit
            return Response.success(CrewMessagePageDto(mine(), null))
        }

        override suspend fun markRead(messageId: String) =
            Response.success(CrewMessageReadDto(messageId, Instant.EPOCH))

        override suspend fun reply(
            messageId: String,
            idempotencyKey: String,
            body: MessageReplyCreateDto
        ) = Response.success(MessageReplyDto("r1", body.presetCode, "Noted", Instant.EPOCH))
    }

    private fun ids() = viewModel.recent.value.map { it.id }

    /** Room answers on its own thread. */
    private fun refreshed() = runBlocking {
        withTimeout(5_000) { viewModel.refreshing.first { !it } }
    }

    @Before
    fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        db = inMemoryDatabase()
        viewModel = CrewMessageViewModel(db.crewDao(), MessagesRepository(api, db.crewDao()))
    }

    @After
    fun tearDown() {
        db.close()
        Dispatchers.resetMain()
    }

    @Test
    fun `opening the tab loads only a few of the crew member's messages`() {
        api.mine = { listOf(message("m2"), message("m1")) }

        viewModel.refresh()

        assertEquals(listOf("m2", "m1"), ids())
        assertEquals(MessagesRepository.RECENT_SIZE, api.askedFor)
    }

    @Test
    fun `no signal keeps the messages already shown`() {
        api.mine = { listOf(message("m1")) }
        viewModel.refresh()

        api.mine = { throw IOException("no signal") }
        viewModel.refresh()

        assertEquals(listOf("m1"), ids())
    }

    @Test
    fun `a sent message goes on top`() {
        api.mine = { listOf(message("m1")) }
        viewModel.refresh()

        viewModel.send("running_late")

        assertEquals(listOf("sent", "m1"), ids())
    }

    @Test
    fun `a retry that returns the same message doesn't repeat it`() {
        viewModel.send("running_late")
        viewModel.send("running_late")

        assertEquals(listOf("sent"), ids())
    }

    @Test
    fun `the list never grows past its size`() {
        api.mine = { List(MessagesRepository.RECENT_SIZE) { message("old-$it") } }
        viewModel.refresh()

        viewModel.send("running_late")

        assertEquals(MessagesRepository.RECENT_SIZE, ids().size)
        assertEquals("sent", ids().first())
    }

    @Test
    fun `a failed send adds nothing`() {
        api.answer = { throw IOException("no signal") }

        viewModel.send("running_late")

        assertEquals(emptyList<String>(), ids())
    }

    @Test
    fun `each message is followed by its replies, oldest first`() {
        val older = message("m1", sentAt = Instant.ofEpochSecond(100))
        val first = MessageReplyDto("r1", "noted", "Noted", Instant.ofEpochSecond(300))
        val second = MessageReplyDto("r2", "van", "Van rerouted", Instant.ofEpochSecond(400))
        val replied =
            message("m2", sentAt = Instant.ofEpochSecond(200), replies = listOf(first, second))

        val rows = recentRows(listOf(replied, older))

        assertEquals(
            listOf(
                RecentRow.Sent(replied),
                RecentRow.Reply("Noted", Instant.ofEpochSecond(300)),
                RecentRow.Reply("Van rerouted", Instant.ofEpochSecond(400)),
                RecentRow.Sent(older)
            ),
            rows
        )
    }

    @Test
    fun `replies never push a message off the list`() {
        val messages = List(MessagesRepository.RECENT_SIZE) { i ->
            val at = Instant.ofEpochSecond(i * 10L)
            val replies = List(3) { MessageReplyDto("r$i-$it", "noted", "Noted", at) }
            message("m$i", sentAt = at, replies = replies)
        }

        val sent = recentRows(messages).filterIsInstance<RecentRow.Sent>()

        assertEquals(messages, sent.map { it.message })
    }

    @Test
    fun `a pull spins until both lists answer, and failing says so`() {
        api.mine = { throw IOException("no signal") }

        viewModel.refresh()
        refreshed()

        assertEquals(true, viewModel.loadFailed.value)
        assertEquals(false, viewModel.recentLoaded.value)
    }

    @Test
    fun `a good refresh clears the failure and marks the list as loaded`() {
        api.mine = { throw IOException("no signal") }
        viewModel.refresh()
        refreshed()
        api.mine = { emptyList() }

        viewModel.refresh()
        refreshed()

        assertEquals(false, viewModel.loadFailed.value)
        assertEquals(true, viewModel.recentLoaded.value)
        assertEquals(false, viewModel.firstLoadPending.value)
    }

    @Test
    fun `seen follows the dispatcher reading the message`() {
        assertEquals(R.string.crew_message_sent_at, sentLine(message("m1")))
        assertEquals(R.string.crew_message_seen_at, sentLine(message("m1", Instant.EPOCH)))
    }
}
