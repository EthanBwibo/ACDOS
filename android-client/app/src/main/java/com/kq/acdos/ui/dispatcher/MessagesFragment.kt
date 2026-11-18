package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import com.kq.acdos.R
import com.kq.acdos.ui.Times
import com.kq.acdos.ui.driver.initials
import kotlinx.coroutines.launch

/**
 * The Messages tab (#250): an inbox with one row per crew member who has
 * messaged, latest activity first, so 100+ crew stay readable. Each row has
 * their name, the last line (theirs or the reply), its time and how many of
 * theirs are unread. A row opens that crew member's thread inside this tab.
 * Nothing is marked read here: only a thread on screen reads messages.
 */
class MessagesFragment : Fragment(R.layout.fragment_messages) {
    private val inbox: InboxViewModel by activityViewModels { InboxViewModel.Factory }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        view.findViewById<ChipGroup>(R.id.filter)
            .setOnCheckedStateChangeListener { _, _ -> showThreads(view) }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                inbox.messages.collect { showThreads(view) }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        home.showTitle(getString(R.string.dispatch_messages))
    }

    private fun showThreads(view: View) {
        val messages = inbox.messages.value ?: return
        val needsReplyOnly = view.findViewById<Chip>(R.id.filter_needs_reply).isChecked
        val threads = inboxRows(crewThreads(messages), needsReplyOnly)
        val emptyText = if (needsReplyOnly) {
            R.string.dispatch_no_needs_reply
        } else {
            R.string.dispatch_no_messages
        }
        view.findViewById<TextView>(R.id.empty).apply {
            isVisible = threads.isEmpty()
            setText(emptyText)
        }
        view.findViewById<View>(R.id.threads_card).isVisible = threads.isNotEmpty()
        val rows = view.findViewById<LinearLayout>(R.id.threads)
        rows.removeAllViews()
        for (thread in threads) {
            val row = rows.addRow(
                title = thread.crewName,
                subtitle = if (thread.lastIsReply) {
                    getString(R.string.dispatch_thread_you, thread.lastLine)
                } else {
                    thread.lastLine
                },
                value = Times.clockWithDay(thread.lastAt),
                lead = initials(thread.crewName)
            ) { open(thread) }
            row.findViewById<Chip>(R.id.row_chip_warning).apply {
                text = thread.unread.toString()
                isVisible = thread.unread > 0
            }
        }
    }

    /** A fresh open starts on their newest unanswered message. */
    private fun open(thread: CrewThread) {
        inbox.openThread(thread.crewMemberId)
        home.open(CrewThreadFragment.of(thread.crewMemberId, thread.crewName))
    }
}
