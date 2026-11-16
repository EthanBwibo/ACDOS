package com.kq.acdos.ui.dispatcher

import android.view.LayoutInflater
import android.view.View
import android.widget.TextView
import androidx.appcompat.view.ContextThemeWrapper
import androidx.core.view.children
import androidx.test.core.app.ApplicationProvider
import com.google.android.material.chip.ChipGroup
import com.kq.acdos.R
import com.kq.acdos.data.remote.PresetMessageDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The reply bar in the real fragment_messages layout, on the app's theme. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ReplyBarTest {
    private val screen: View = LayoutInflater
        .from(ContextThemeWrapper(ApplicationProvider.getApplicationContext(), R.style.Theme_ACDOS))
        .inflate(R.layout.fragment_messages, null)

    private val bar = screen.findViewById<View>(R.id.reply_group)

    private val presets = listOf(PresetMessageDto("noted", "Noted"), PresetMessageDto("van", "Van"))

    private val sent = mutableListOf<String>()
    private var retries = 0

    private fun show(replyTo: String?, failed: Boolean = false, sending: Boolean = false) =
        bindReplyBar(bar, ReplyBarState(replyTo, presets, failed, sending), { sent += it }) {
            retries++
        }

    private fun chips() = screen.findViewById<ChipGroup>(R.id.reply_presets).children.toList()

    private fun text(id: Int) = screen.findViewById<TextView>(id).text.toString()

    @Test
    fun `with no message selected the bar is visible and asks for a tap`() {
        show(replyTo = null)

        assertEquals(View.VISIBLE, bar.visibility)
        assertEquals("Tap a message to reply", text(R.id.reply_to))
        assertEquals(2, chips().size)
        assertTrue(chips().none { it.isEnabled })
    }

    @Test
    fun `with a message selected it names the crew member and the chips send`() {
        show(replyTo = "Brian Mwangi")

        assertEquals("Reply to Brian Mwangi", text(R.id.reply_to))
        assertTrue(chips().all { it.isEnabled })
        chips().first().performClick()
        assertEquals(listOf("noted"), sent)
    }

    @Test
    fun `while a reply is sending the chips are disabled`() {
        show(replyTo = "Brian Mwangi", sending = true)

        assertTrue(chips().none { it.isEnabled })
    }

    @Test
    fun `replies that failed to load show an error with Retry instead of chips`() {
        show(replyTo = "Brian Mwangi", failed = true)

        assertEquals(View.VISIBLE, screen.findViewById<View>(R.id.reply_presets_error).visibility)
        assertEquals(View.GONE, screen.findViewById<View>(R.id.reply_presets).visibility)
        screen.findViewById<View>(R.id.reply_presets_retry).performClick()
        assertEquals(1, retries)
    }
}
