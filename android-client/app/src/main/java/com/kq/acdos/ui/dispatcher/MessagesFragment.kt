package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import com.kq.acdos.R
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.ui.Times
import kotlinx.coroutines.launch

/**
 * Crew messages, newest first (Figma 2:241). Tapping one marks it read. All
 * messaging goes through the dispatcher, and only crew send messages, so
 * there's no Drivers filter or Forward to driver.
 */
class MessagesFragment : Fragment(R.layout.fragment_messages) {
    private val inbox: InboxViewModel by activityViewModels { InboxViewModel.Factory }

    private var messages: List<CrewMessageDto>? = null

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        home.showTitle(getString(R.string.dispatch_messages))
        val filter = view.findViewById<ChipGroup>(R.id.filter)
        filter.setOnCheckedStateChangeListener { _, _ -> show(view) }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                inbox.messages.collect {
                    messages = it
                    show(view)
                }
            }
        }
    }

    private fun show(view: View) {
        val rows = view.findViewById<LinearLayout>(R.id.messages)
        rows.removeAllViews()
        val all = messages ?: return
        val unreadOnly = view.findViewById<Chip>(R.id.filter_unread).isChecked
        val shown = if (unreadOnly) all.filter { it.readAt == null } else all
        for (message in shown) {
            val row = rows.addRow(
                title = message.crewName,
                subtitle = getString(R.string.dispatch_message_quote, message.label),
                value = Times.shortClock(message.sentAt)
            ) { inbox.markRead(message.id) }
            row.findViewById<View>(R.id.row_chip_neutral).apply {
                isVisible = message.readAt == null
                (this as Chip).setText(R.string.dispatch_message_new)
            }
        }
        if (shown.isEmpty()) rows.addRow(getString(R.string.dispatch_none))
    }
}
