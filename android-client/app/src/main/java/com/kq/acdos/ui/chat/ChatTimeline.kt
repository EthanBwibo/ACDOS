package com.kq.acdos.ui.chat

import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.ui.Times
import java.time.Instant
import java.time.LocalDate

/** Who sent a chat line. Crew send presets; the dispatcher sends preset replies. */
enum class Sender { CREW, DISPATCHER }

/** One row of the conversation shown by [ChatAdapter]. */
sealed interface ChatItem {
    /** "Today" or "Wed 11 Nov", above the first line sent that day in Nairobi. */
    data class Day(val date: LocalDate) : ChatItem

    data class Bubble(
        /** Unique across messages and replies, for the RecyclerView's diffing. */
        val key: String,
        /** The crew message this line is, or answers. The dispatcher replies to this id. */
        val messageId: String,
        val sender: Sender,
        val text: String,
        val crewName: String,
        val at: Instant,
        /** When the dispatcher read it. Only crew messages have one. */
        val readAt: Instant?,
        /** Sent by the person looking at the screen: drawn on the right. */
        val mine: Boolean
    ) : ChatItem
}

/**
 * The conversation, oldest first so the newest line is at the bottom. Each
 * crew message is followed by the dispatcher's replies to it, sorted here by
 * sentAt rather than trusting the server's order. On the dispatcher's screen a
 * reply always sits right under the message it answers.
 *
 * Which side a line goes on comes from [viewer] against the line's sender,
 * never from its text.
 */
fun chatTimeline(messages: List<CrewMessageDto>, viewer: Sender): List<ChatItem> {
    val bubbles = messages.sortedBy { it.sentAt }.flatMap { message ->
        val sent = ChatItem.Bubble(
            key = "m:${message.id}",
            messageId = message.id,
            sender = Sender.CREW,
            text = message.label,
            crewName = message.crewName,
            at = message.sentAt,
            readAt = message.readAt,
            mine = viewer == Sender.CREW
        )
        val replies = message.replies.sortedBy { it.sentAt }.map { reply ->
            ChatItem.Bubble(
                key = "r:${reply.id}",
                messageId = message.id,
                sender = Sender.DISPATCHER,
                text = reply.label,
                crewName = message.crewName,
                at = reply.sentAt,
                readAt = null,
                mine = viewer == Sender.DISPATCHER
            )
        }
        listOf(sent) + replies
    }
    val items = mutableListOf<ChatItem>()
    var day: LocalDate? = null
    for (bubble in bubbles) {
        val date = Times.date(bubble.at)
        if (date != day) {
            items += ChatItem.Day(date)
            day = date
        }
        items += bubble
    }
    return items
}
