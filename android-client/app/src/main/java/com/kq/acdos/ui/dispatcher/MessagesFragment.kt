package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.LayoutInflater
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
import com.google.android.material.color.MaterialColors
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.R
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.ui.Times
import kotlinx.coroutines.launch

/**
 * Crew messages, newest first (Figma 2:241). Tapping one marks it read and
 * opens the preset replies, which go only to that crew member. Only crew send
 * messages, so there's no Drivers filter or Forward to driver.
 */
class MessagesFragment : Fragment(R.layout.fragment_messages) {
    private val inbox: InboxViewModel by activityViewModels { InboxViewModel.Factory }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        home.showTitle(getString(R.string.dispatch_messages))
        val filter = view.findViewById<ChipGroup>(R.id.filter)
        filter.setOnCheckedStateChangeListener { _, _ -> showMessages(view) }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                inbox.messages.collect { showMessages(view) }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                inbox.selected.collect { showMessages(view) }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                inbox.replyPresets.collect { showPresets(view) }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                inbox.replying.collect { showPresets(view) }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                inbox.notices.collect { Snackbar.make(view, it, Snackbar.LENGTH_LONG).show() }
            }
        }
    }

    private fun showMessages(view: View) {
        val rows = view.findViewById<LinearLayout>(R.id.messages)
        rows.removeAllViews()
        val all = inbox.messages.value ?: return
        val unreadOnly = view.findViewById<Chip>(R.id.filter_unread).isChecked
        val shown = if (unreadOnly) all.filter { it.readAt == null } else all
        shown.forEach { addMessage(rows, it) }
        if (shown.isEmpty()) rows.addRow(getString(R.string.dispatch_none))

        val selected = all.firstOrNull { it.id == inbox.selected.value }
        view.findViewById<View>(R.id.reply_group).isVisible = selected != null
        view.findViewById<TextView>(R.id.reply_to).text =
            selected?.let { getString(R.string.dispatch_reply_to, it.crewName) }
    }

    private fun addMessage(rows: LinearLayout, message: CrewMessageDto) {
        val quote = getString(R.string.dispatch_message_quote, message.label)
        val replied = message.replies.joinToString(" · ") { it.label }
        val row = rows.addRow(
            title = message.crewName,
            subtitle = if (replied.isEmpty()) {
                quote
            } else {
                quote + "\n" + getString(R.string.dispatch_replied, replied)
            },
            value = Times.shortClock(message.sentAt)
        ) { inbox.select(message.id) }
        row.findViewById<Chip>(R.id.row_chip_neutral).apply {
            isVisible = message.readAt == null
            setText(R.string.dispatch_message_new)
        }
        if (message.id == inbox.selected.value) {
            row.setBackgroundColor(
                MaterialColors.getColor(
                    row,
                    com.google.android.material.R.attr.colorSurfaceContainer
                )
            )
        }
    }

    private fun showPresets(view: View) {
        val chips = view.findViewById<ChipGroup>(R.id.reply_presets)
        chips.removeAllViews()
        val inflater = LayoutInflater.from(chips.context)
        for (preset in inbox.replyPresets.value) {
            val chip = inflater.inflate(R.layout.item_reply_chip, chips, false) as Chip
            chip.text = preset.label
            chip.isEnabled = !inbox.replying.value
            chip.setOnClickListener { inbox.reply(preset.code) }
            chips.addView(chip)
        }
    }
}
