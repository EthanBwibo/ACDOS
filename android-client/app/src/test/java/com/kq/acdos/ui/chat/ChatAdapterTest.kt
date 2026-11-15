package com.kq.acdos.ui.chat

import android.content.Context
import android.view.View
import android.widget.FrameLayout
import android.widget.TextView
import androidx.appcompat.view.ContextThemeWrapper
import androidx.test.core.app.ApplicationProvider
import com.kq.acdos.R
import com.kq.acdos.data.remote.MessageReplyDto
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ChatAdapterTest {
    private val context: Context =
        ContextThemeWrapper(ApplicationProvider.getApplicationContext(), R.style.Theme_ACDOS)

    private val reply = MessageReplyDto("r1", "noted", "Noted", nairobi(6))
    private val messages = listOf(
        crewMessage("m1", nairobi(5), readAt = nairobi(5), replies = listOf(reply))
    )

    /** Day header, crew message, dispatcher reply. */
    private fun adapterFor(viewer: Sender) = ChatAdapter(now = { nairobi(9) }).apply {
        // The first list goes in without a background diff, so it's there at once.
        submitList(chatTimeline(messages, viewer))
    }

    private fun bind(adapter: ChatAdapter, position: Int): View {
        val parent = FrameLayout(context)
        val holder = adapter.onCreateViewHolder(parent, adapter.getItemViewType(position))
        adapter.onBindViewHolder(holder, position)
        return holder.itemView
    }

    @Test
    fun `for crew, their own message is mine and the dispatcher's reply is theirs`() {
        val adapter = adapterFor(Sender.CREW)

        assertEquals(ChatAdapter.TYPE_DAY, adapter.getItemViewType(0))
        assertEquals(ChatAdapter.TYPE_MINE, adapter.getItemViewType(1))
        assertEquals(ChatAdapter.TYPE_THEIRS, adapter.getItemViewType(2))
    }

    @Test
    fun `for the dispatcher, the same lines swap sides`() {
        val adapter = adapterFor(Sender.DISPATCHER)

        assertEquals(ChatAdapter.TYPE_THEIRS, adapter.getItemViewType(1))
        assertEquals(ChatAdapter.TYPE_MINE, adapter.getItemViewType(2))
    }

    @Test
    fun `the dispatcher sees whose message it is, crew never see a name`() {
        val forDispatcher = bind(adapterFor(Sender.DISPATCHER), 1)
        val forCrew = bind(adapterFor(Sender.CREW), 2)

        val name = forDispatcher.findViewById<TextView>(R.id.bubble_sender)
        assertEquals(View.VISIBLE, name.visibility)
        assertEquals("A. Sample", name.text)
        assertEquals(View.GONE, forCrew.findViewById<View>(R.id.bubble_sender).visibility)
    }

    @Test
    fun `the time and seen go under the bubble, and today is labelled Today`() {
        val adapter = adapterFor(Sender.CREW)

        val meta = bind(adapter, 1).findViewById<TextView>(R.id.bubble_meta)
        val header = bind(adapter, 0) as TextView

        assertEquals("05:00 · Seen", meta.text)
        assertEquals("Today", header.text)
    }
}
