package com.kq.acdos.ui.crew

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.R
import com.kq.acdos.data.local.PresetMessageEntity
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.ui.chat.ChatAdapter
import com.kq.acdos.ui.chat.Sender
import com.kq.acdos.ui.chat.chatTimeline
import com.kq.acdos.ui.useThemeColors
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * Messages to the dispatcher (#57, Figma 3:372): one chip per preset, and the
 * conversation as chat bubbles (#226), newest at the bottom. There is no text
 * field anywhere: crew can only send a preset, and only to the dispatcher.
 */
class CrewMessageFragment : Fragment(R.layout.fragment_crew_message) {
    private val viewModel: CrewMessageViewModel by viewModels { CrewMessageViewModel.Factory }
    private val chat = ChatAdapter()

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        (requireActivity() as CrewHomeActivity).showTitle(R.string.crew_message_title)
        val list = view.findViewById<ChipGroup>(R.id.presets)
        val empty = view.findViewById<TextView>(R.id.empty)
        val conversation = view.findViewById<RecyclerView>(R.id.conversation)
        conversation.layoutManager = LinearLayoutManager(view.context).apply { stackFromEnd = true }
        conversation.adapter = chat
        val swipe = view.findViewById<SwipeRefreshLayout>(R.id.swipe_refresh)
        swipe.useThemeColors()
        // The list isn't the refresh layout's direct child, so say when it can still scroll up.
        swipe.setOnChildScrollUpCallback { _, _ -> conversation.canScrollVertically(-1) }
        swipe.setOnRefreshListener {
            if (!viewModel.refresh()) swipe.isRefreshing = false
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.presets.collect { presets ->
                    list.removeAllViews()
                    presets.forEach { list.addView(presetChip(list, it)) }
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(
                    viewModel.presets,
                    viewModel.firstLoadPending,
                    viewModel.loadFailed,
                    viewModel.refreshing
                ) { presets, firstLoad, failed, refreshing ->
                    Triple(refreshing || firstLoad, failed, presets.isEmpty() && !firstLoad)
                }.collect { (spinner, failed, noPresets) ->
                    swipe.isRefreshing = spinner
                    view.findViewById<View>(R.id.error).isVisible = failed
                    empty.isVisible = noPresets && !failed
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(viewModel.recent, viewModel.recentLoaded, ::Pair).collect {
                    showConversation(view, conversation, it.first, it.second)
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.sending.collect { sending ->
                    for (i in 0 until list.childCount) {
                        list.getChildAt(i).isEnabled = !sending
                    }
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.messages.collect { message ->
                    Snackbar.make(view, message, Snackbar.LENGTH_LONG)
                        .setAnchorView(requireActivity().findViewById(R.id.bottom_nav))
                        .show()
                }
            }
        }
    }

    private fun presetChip(list: ChipGroup, preset: PresetMessageEntity): Chip {
        val inflater = LayoutInflater.from(list.context)
        val chip = inflater.inflate(R.layout.item_reply_chip, list, false) as Chip
        chip.text = preset.label
        chip.isEnabled = !viewModel.sending.value
        chip.setOnClickListener { viewModel.send(preset.code) }
        return chip
    }

    private fun showConversation(
        view: View,
        conversation: RecyclerView,
        messages: List<CrewMessageDto>,
        loaded: Boolean
    ) {
        view.findViewById<View>(R.id.recent_empty).isVisible = messages.isEmpty() && loaded
        chat.submitList(chatTimeline(messages, Sender.CREW)) {
            if (chat.itemCount > 0) conversation.scrollToPosition(chat.itemCount - 1)
        }
    }

    override fun onStart() {
        super.onStart()
        viewModel.refresh()
    }
}
