package com.kq.acdos.ui.dispatcher

import com.kq.acdos.data.remote.CrewMessageDto
import java.time.Instant

/** One row of the dispatcher's inbox (#250): a crew member who has messaged. */
data class CrewThread(
    val crewMemberId: String,
    val crewName: String,
    /** The newest line in the thread: their message or the dispatcher's reply. */
    val lastLine: String,
    /** True when [lastLine] is the dispatcher's reply. */
    val lastIsReply: Boolean,
    val lastAt: Instant,
    /** Their messages the dispatcher hasn't read. */
    val unread: Int,
    /** At least one of their messages has no reply yet. */
    val needsReply: Boolean
)

/**
 * The inbox, built in the app from the message list: one thread per crew
 * member, latest activity first. A reply counts as activity, so answering
 * someone moves them up as well.
 */
fun crewThreads(messages: List<CrewMessageDto>): List<CrewThread> =
    messages.groupBy { it.crewMemberId }.map { (crewMemberId, theirs) ->
        val newest = theirs.maxBy { it.sentAt }
        val newestReply = theirs.flatMap { it.replies }.maxByOrNull { it.sentAt }
        val replyIsLast = newestReply != null && newestReply.sentAt > newest.sentAt
        CrewThread(
            crewMemberId = crewMemberId,
            crewName = newest.crewName,
            lastLine = if (replyIsLast) newestReply!!.label else newest.label,
            lastIsReply = replyIsLast,
            lastAt = if (replyIsLast) newestReply!!.sentAt else newest.sentAt,
            unread = theirs.count { it.readAt == null },
            needsReply = theirs.any { it.replies.isEmpty() }
        )
    }.sortedByDescending { it.lastAt }

/** The inbox rows under a filter chip: All, or only those who need a reply. */
fun inboxRows(threads: List<CrewThread>, needsReplyOnly: Boolean): List<CrewThread> =
    if (needsReplyOnly) threads.filter { it.needsReply } else threads

/** One crew member's messages, for their thread. */
fun threadMessages(messages: List<CrewMessageDto>, crewMemberId: String?): List<CrewMessageDto> =
    messages.filter { it.crewMemberId == crewMemberId }
