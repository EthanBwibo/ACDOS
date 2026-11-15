package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.R
import com.kq.acdos.ui.chat.ChatAdapter
import com.kq.acdos.ui.chat.Sender
import com.kq.acdos.ui.chat.chatTimeline
import kotlinx.coroutines.launch

/**
 * Crew messages as chat bubbles, newest at the bottom (Figma 2:241, #226).
 * Tapping a crew message marks it read and opens the preset replies, which go
 * only to that crew member. Only crew send
 * messages, so there's no Drivers filter or Forward to driver.
 */
class MessagesFragment : Fragment(R.layout.fragment_messages) {
    private val inbox: InboxViewModel by activityViewModels { InboxViewModel.Factory }
    private val chat = ChatAdapter(onCrewMessageTap = { inbox.select(it.messageId) })

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        home.showTitle(getString(R.string.dispatch_messages))
        val conversation = view.findViewById<RecyclerView>(R.id.conversation)
        conversation.layoutManager = LinearLayoutManager(view.context).apply { stackFromEnd = true }
        conversation.adapter = chat
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
        val all = inbox.messages.value ?: return
        val unreadOnly = view.findViewById<Chip>(R.id.filter_unread).isChecked
        val shown = if (unreadOnly) all.filter { it.readAt == null } else all
        view.findViewById<TextView>(R.id.empty).apply {
            isVisible = shown.isEmpty()
            setText(if (unreadOnly) R.string.dispatch_no_unread else R.string.dispatch_no_messages)
        }
        val conversation = view.findViewById<RecyclerView>(R.id.conversation)
        val items = chatTimeline(shown, Sender.DISPATCHER)
        // Jump to the newest line when lines come or go, not when a tap only selects one.
        val changed = items.size != chat.itemCount
        chat.selectedMessageId = inbox.selected.value
        chat.submitList(items) {
            if (changed && items.isNotEmpty()) conversation.scrollToPosition(items.size - 1)
        }

        val selected = all.firstOrNull { it.id == inbox.selected.value }
        view.findViewById<View>(R.id.reply_group).isVisible = selected != null
        view.findViewById<TextView>(R.id.reply_to).text =
            selected?.let { getString(R.string.dispatch_reply_to, it.crewName) }
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
