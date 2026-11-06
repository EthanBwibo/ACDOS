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
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.R
import com.kq.acdos.data.local.PresetMessageEntity
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.ui.Times
import kotlinx.coroutines.launch

/** "Sent 05:20 EAT", with "seen" once the dispatcher has read the message. */
@StringRes
fun sentLine(message: CrewMessageDto): Int =
    if (message.readAt != null) R.string.crew_message_seen_at else R.string.crew_message_sent_at

/**
 * Messages to the dispatcher (#57, Figma 3:372): one button per preset, and
 * what was sent. There is no text field anywhere: crew can only send a preset,
 * and only to the dispatcher.
 */
class CrewMessageFragment : Fragment(R.layout.fragment_crew_message) {
    private val viewModel: CrewMessageViewModel by viewModels { CrewMessageViewModel.Factory }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        (requireActivity() as CrewHomeActivity).showTitle(R.string.crew_message_title)
        val list = view.findViewById<LinearLayout>(R.id.presets)
        val empty = view.findViewById<TextView>(R.id.empty)

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.presets.collect { presets ->
                    list.removeAllViews()
                    empty.isVisible = presets.isEmpty()
                    presets.forEach { list.addView(presetButton(list, it)) }
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.recent.collect { showRecent(view, it) }
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

    private fun showRecent(view: View, messages: List<CrewMessageDto>) {
        view.findViewById<View>(R.id.recent_label).isVisible = messages.isNotEmpty()
        view.findViewById<View>(R.id.recent_card).isVisible = messages.isNotEmpty()
        val rows = view.findViewById<LinearLayout>(R.id.recent_rows)
        rows.removeAllViews()
        for (message in messages) {
            val row = LayoutInflater.from(rows.context).inflate(R.layout.item_list_row, rows, false)
            row.findViewById<TextView>(R.id.row_title).text =
                getString(R.string.crew_message_row, message.label)
            row.findViewById<TextView>(R.id.row_subtitle).text =
                getString(sentLine(message), Times.clockWithDay(message.sentAt))
            row.findViewById<View>(R.id.row_value).isVisible = false
            rows.addView(row)
        }
    }

    override fun onStart() {
        super.onStart()
        viewModel.refresh()
    }
}
