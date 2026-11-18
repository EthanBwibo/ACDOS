package com.kq.acdos.ui.dispatcher

import android.os.Bundle
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
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.R
import com.kq.acdos.ui.chat.ChatAdapter
import com.kq.acdos.ui.chat.Sender
import com.kq.acdos.ui.chat.chatTimeline
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * One crew member's thread (#250), opened from the inbox inside the Messages
 * tab: their messages and the replies as chat bubbles, newest at the bottom
 * (Figma 2:241, #226), with the reply bar under them. The reply bar starts on
 * their newest unanswered message; tapping another of theirs picks it
 * instead. Whatever is selected while this thread is shown counts as read.
 */
class CrewThreadFragment : Fragment(R.layout.fragment_crew_thread) {
    private val inbox: InboxViewModel by activityViewModels { InboxViewModel.Factory }
    private val chat = ChatAdapter(onCrewMessageTap = { inbox.select(it.messageId) })

    private val crewMemberId get() = requireArguments().getString(ARG_CREW_MEMBER_ID)!!

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Restored after the process was killed: the inbox starts again with no thread open.
        if (inbox.thread.value != crewMemberId) inbox.openThread(crewMemberId)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val conversation = view.findViewById<RecyclerView>(R.id.conversation)
        conversation.layoutManager = LinearLayoutManager(view.context).apply { stackFromEnd = true }
        conversation.adapter = chat

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(inbox.messages, inbox.selected, ::Pair).collect { showMessages(view) }
            }
        }
        val bar = view.findViewById<View>(R.id.reply_group)
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(
                    inbox.messages,
                    inbox.selected,
                    inbox.replyPresets,
                    inbox.presetsFailed,
                    inbox.replying
                ) { messages, selected, presets, failed, sending ->
                    val replyTo = messages.orEmpty().firstOrNull { it.id == selected }?.crewName
                    ReplyBarState(replyTo, presets, failed, sending)
                }.collect { state ->
                    bindReplyBar(bar, state, inbox::reply, inbox::loadPresets)
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                inbox.notices.collect { Snackbar.make(view, it, Snackbar.LENGTH_LONG).show() }
            }
        }
    }

    // Selecting a message counts as reading it only while this thread is shown.
    // onStop also comes when another tab is picked: the activity holds hidden tabs at
    // CREATED (#230). The title is set here too, so it comes back with the tab.
    override fun onStart() {
        super.onStart()
        home.showTitle(requireArguments().getString(ARG_CREW_NAME).orEmpty())
        inbox.setShown(true)
    }

    override fun onStop() {
        inbox.setShown(false)
        super.onStop()
    }

    private fun showMessages(view: View) {
        val all = inbox.messages.value ?: return
        val shown = threadMessages(all, crewMemberId)
        view.findViewById<TextView>(R.id.empty).apply {
            isVisible = shown.isEmpty()
            setText(R.string.dispatch_no_messages)
        }
        val conversation = view.findViewById<RecyclerView>(R.id.conversation)
        val items = chatTimeline(shown, Sender.DISPATCHER)
        // Jump to the newest line when lines come or go, not when a tap only selects one.
        val changed = items.size != chat.itemCount
        chat.selectedMessageId = inbox.selected.value
        chat.submitList(items) {
            if (changed && items.isNotEmpty()) conversation.scrollToPosition(items.size - 1)
        }
    }

    companion object {
        private const val ARG_CREW_MEMBER_ID = "crew_member_id"
        private const val ARG_CREW_NAME = "crew_name"

        fun of(crewMemberId: String, crewName: String) = CrewThreadFragment().apply {
            arguments = Bundle().apply {
                putString(ARG_CREW_MEMBER_ID, crewMemberId)
                putString(ARG_CREW_NAME, crewName)
            }
        }
    }
}
