package com.kq.acdos.ui.dispatcher

import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.data.remote.MessageReplyDto
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Test

private val T0: Instant = Instant.parse("2026-11-19T03:00:00Z")

private fun at(minutes: Long): Instant = T0.plusSeconds(minutes * 60)

private fun from(
    crew: String,
    id: String,
    minutes: Long,
    read: Boolean = false,
    reply: Long? = null
) = CrewMessageDto(
    id = id,
    crewMemberId = crew,
    crewName = crew.replaceFirstChar { it.uppercaseChar() },
    presetCode = "late",
    label = "Running late",
    sentAt = at(minutes),
    readAt = if (read) at(minutes) else null,
    replies = reply?.let { listOf(MessageReplyDto("r-$id", "noted", "Noted", at(it))) }.orEmpty()
)

/** The dispatcher's per-crew inbox (#250), built from the message list. */
class CrewThreadsTest {
    @Test
    fun theInboxOrdersByLatestActivity_aReplyCounting() {
        val messages = listOf(
            from("amina", "a1", minutes = 10),
            from("brian", "b1", minutes = 5, read = true, reply = 20),
            from("chao", "c1", minutes = 1)
        )

        val threads = crewThreads(messages)

        assertEquals(listOf("brian", "amina", "chao"), threads.map { it.crewMemberId })
        assertEquals(at(20), threads[0].lastAt)
    }

    @Test
    fun theLastLineIsTheirsOrTheReply_whicheverIsNewer() {
        val replied = crewThreads(listOf(from("brian", "b1", minutes = 5, reply = 20))).single()
        val newer = crewThreads(
            listOf(from("amina", "a1", minutes = 1, reply = 2), from("amina", "a2", minutes = 3))
        ).single()

        assertEquals("Noted" to true, replied.lastLine to replied.lastIsReply)
        assertEquals("Running late" to false, newer.lastLine to newer.lastIsReply)
        assertEquals(at(3), newer.lastAt)
    }

    @Test
    fun eachThreadCountsOnlyItsOwnUnread() {
        val messages = listOf(
            from("amina", "a1", minutes = 1),
            from("amina", "a2", minutes = 2),
            from("amina", "a3", minutes = 3, read = true),
            from("brian", "b1", minutes = 4, read = true)
        )

        val unread = crewThreads(messages).associate { it.crewMemberId to it.unread }

        assertEquals(mapOf("brian" to 0, "amina" to 2), unread)
    }

    @Test
    fun needsReplyKeepsOnlyThreadsWithAnUnansweredMessage() {
        val messages = listOf(
            from("amina", "a1", minutes = 1, reply = 2),
            from("amina", "a2", minutes = 3),
            from("brian", "b1", minutes = 4, reply = 5),
            from("chao", "c1", minutes = 6)
        )
        val threads = crewThreads(messages)

        assertEquals(listOf("chao", "amina"), inboxRows(threads, true).map { it.crewMemberId })
        assertEquals(3, inboxRows(threads, false).size)
    }

    @Test
    fun aThreadHoldsOnlyThatCrewMembersMessages() {
        val messages = listOf(from("amina", "a1", 1), from("brian", "b1", 2))

        assertEquals(listOf("a1"), threadMessages(messages, "amina").map { it.id })
        assertEquals(emptyList<CrewMessageDto>(), threadMessages(messages, null))
    }
}
