package com.kq.acdos.ui.crew

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.annotation.StringRes
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.R
import com.kq.acdos.data.local.PresetMessageEntity
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.ui.Times
import com.kq.acdos.ui.useThemeColors
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/** "Sent 05:20 EAT", with "seen" once the dispatcher has read the message. */
@StringRes
fun sentLine(message: CrewMessageDto): Int =
    if (message.readAt != null) R.string.crew_message_seen_at else R.string.crew_message_sent_at

/**
 * Messages to the dispatcher (#57, Figma 3:372): one button per preset, and
 * what was sent, with the dispatcher's replies. There is no text field
 * anywhere: crew can only send a preset, and only to the dispatcher.
 */
class CrewMessageFragment : Fragment(R.layout.fragment_crew_message) {
    private val viewModel: CrewMessageViewModel by viewModels { CrewMessageViewModel.Factory }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        (requireActivity() as CrewHomeActivity).showTitle(R.string.crew_message_title)
        val list = view.findViewById<LinearLayout>(R.id.presets)
        val empty = view.findViewById<TextView>(R.id.empty)
        val swipe = view.findViewById<SwipeRefreshLayout>(R.id.swipe_refresh)
        swipe.useThemeColors()
        swipe.setOnRefreshListener {
            if (!viewModel.refresh()) swipe.isRefreshing = false
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.presets.collect { presets ->
                    list.removeAllViews()
                    presets.forEach { list.addView(presetButton(list, it)) }
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
                    showRecent(view, it.first, it.second)
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.sending.collect { sending ->
                    for (i in 0 until list.childCount) {
                        (list.getChildAt(i) as Button).isEnabled = !sending
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

    private fun presetButton(list: LinearLayout, preset: PresetMessageEntity): Button {
        val inflater = LayoutInflater.from(list.context)
        val button = inflater.inflate(R.layout.item_preset_button, list, false) as Button
        button.text = preset.label
        button.isEnabled = !viewModel.sending.value
        button.setOnClickListener { viewModel.send(preset.code) }
        return button
    }

    private fun showRecent(view: View, messages: List<CrewMessageDto>, loaded: Boolean) {
        view.findViewById<View>(R.id.recent_label).isVisible = messages.isNotEmpty() || loaded
        view.findViewById<View>(R.id.recent_empty).isVisible = messages.isEmpty() && loaded
        view.findViewById<View>(R.id.recent_card).isVisible = messages.isNotEmpty()
        val rows = view.findViewById<LinearLayout>(R.id.recent_rows)
        rows.removeAllViews()
        for (recent in recentRows(messages)) {
            val row = LayoutInflater.from(rows.context).inflate(R.layout.item_list_row, rows, false)
            row.findViewById<TextView>(R.id.row_title).text = when (recent) {
                is RecentRow.Sent -> getString(R.string.crew_message_row, recent.message.label)
                is RecentRow.Reply -> getString(R.string.crew_message_reply_row, recent.label)
            }
            val at = Times.clockWithDay(recent.at)
            row.findViewById<TextView>(R.id.row_subtitle).text = when (recent) {
                is RecentRow.Sent -> getString(sentLine(recent.message), at)
                is RecentRow.Reply -> at
            }
            row.findViewById<View>(R.id.row_value).isVisible = false
            rows.addView(row)
        }
    }

    override fun onStart() {
        super.onStart()
        viewModel.refresh()
    }
}
