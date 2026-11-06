package com.kq.acdos.ui.crew

import com.kq.acdos.R
import com.kq.acdos.data.MessagesRepository
import com.kq.acdos.data.local.AcdosDatabase
import com.kq.acdos.data.local.inMemoryDatabase
import com.kq.acdos.data.remote.CrewMessageCreateDto
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.data.remote.CrewMessagePageDto
import com.kq.acdos.data.remote.CrewMessageReadDto
import com.kq.acdos.data.remote.MessagesApi
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
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import retrofit2.Response

private fun message(id: String, readAt: Instant? = null) = CrewMessageDto(
    id = id,
    crewMemberId = "crew-1",
    crewName = "A. Sample",
    presetCode = "running_late",
    label = "I am running late",
    sentAt = Instant.EPOCH,
    readAt = readAt,
    replies = emptyList()
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
    }

    private fun ids() = viewModel.recent.value.map { it.id }

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
    fun `seen follows the dispatcher reading the message`() {
        assertEquals(R.string.crew_message_sent_at, sentLine(message("m1")))
        assertEquals(R.string.crew_message_seen_at, sentLine(message("m1", Instant.EPOCH)))
    }
}
