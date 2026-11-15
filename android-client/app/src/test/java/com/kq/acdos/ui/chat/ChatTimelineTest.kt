package com.kq.acdos.ui.chat

import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.data.remote.MessageReplyDto
import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneOffset
import org.junit.Assert.assertEquals
import org.junit.Test

internal fun crewMessage(
    id: String,
    sentAt: Instant,
    readAt: Instant? = null,
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

/** 20 Nov 2026 at [hour]:00 in Nairobi (UTC+3). */
internal fun nairobi(hour: Int, day: Int = 20): Instant =
    OffsetDateTime.of(2026, 11, day, hour, 0, 0, 0, ZoneOffset.ofHours(3)).toInstant()

class ChatTimelineTest {
    @Test
    fun `oldest first, each message followed by its replies, under one day header`() {
        val reply = MessageReplyDto("r1", "noted", "Noted", nairobi(6))
        val newer = crewMessage("m2", nairobi(7))
        val older = crewMessage("m1", nairobi(5), replies = listOf(reply))

        // The API sends newest first.
        val items = chatTimeline(listOf(newer, older), Sender.CREW)

        assertEquals(
            listOf("day", "m:m1", "r:r1", "m:m2"),
            items.map { (it as? ChatItem.Bubble)?.key ?: "day" }
        )
        assertEquals(ChatItem.Day(LocalDate.of(2026, 11, 20)), items.first())
    }

    @Test
    fun `a new Nairobi day gets its own header`() {
        // 23:00 on the 20th and 01:00 on the 21st, Nairobi time: the same UTC day.
        val late = crewMessage("m1", nairobi(23))
        val early = crewMessage("m2", nairobi(1, day = 21))

        val days = chatTimeline(listOf(early, late), Sender.CREW)
            .filterIsInstance<ChatItem.Day>()
            .map { it.date }

        assertEquals(listOf(LocalDate.of(2026, 11, 20), LocalDate.of(2026, 11, 21)), days)
    }

    @Test
    fun `the side comes from the viewer against the sender`() {
        val reply = MessageReplyDto("r1", "noted", "Noted", nairobi(6))
        val messages = listOf(crewMessage("m1", nairobi(5), replies = listOf(reply)))

        fun sides(viewer: Sender) = chatTimeline(messages, viewer)
            .filterIsInstance<ChatItem.Bubble>()
            .map { it.sender to it.mine }

        assertEquals(
            listOf(Sender.CREW to true, Sender.DISPATCHER to false),
            sides(Sender.CREW)
        )
        assertEquals(
            listOf(Sender.CREW to false, Sender.DISPATCHER to true),
            sides(Sender.DISPATCHER)
        )
    }

    @Test
    fun `a reply answers its own message`() {
        val reply = MessageReplyDto("r1", "noted", "Noted", nairobi(6))
        val messages = listOf(crewMessage("m1", nairobi(5), replies = listOf(reply)))

        val bubble = chatTimeline(messages, Sender.DISPATCHER).last() as ChatItem.Bubble

        assertEquals("m1", bubble.messageId)
    }
}
