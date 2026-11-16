package com.kq.acdos.ui.dispatcher

import android.view.LayoutInflater
import android.view.View
import android.widget.TextView
import androidx.core.view.isVisible
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import com.kq.acdos.R
import com.kq.acdos.data.remote.PresetMessageDto

/** What the reply bar under the dispatcher's conversation shows. */
data class ReplyBarState(
    /** The crew member the selected message is from; null when none is selected. */
    val replyTo: String?,
    val presets: List<PresetMessageDto>,
    val presetsFailed: Boolean,
    /** A reply is on its way, so the chips can't send a second one. */
    val sending: Boolean
)

/**
 * Fills the reply bar (`R.id.reply_group` in fragment_messages.xml). The bar
 * is always there: with no message selected it says how to pick one and its
 * chips are disabled; if the replies failed to load it shows an error with
 * Retry in place of the chips.
 */
fun bindReplyBar(bar: View, state: ReplyBarState, onPreset: (String) -> Unit, onRetry: () -> Unit) {
    bar.isVisible = true
    val context = bar.context
    bar.findViewById<TextView>(R.id.reply_to).text = state.replyTo
        ?.let { context.getString(R.string.dispatch_reply_to, it) }
        ?: context.getString(R.string.dispatch_reply_pick)

    val chips = bar.findViewById<ChipGroup>(R.id.reply_presets)
    val error = bar.findViewById<View>(R.id.reply_presets_error)
    error.isVisible = state.presetsFailed
    chips.isVisible = !state.presetsFailed
    bar.findViewById<View>(R.id.reply_presets_retry).setOnClickListener { onRetry() }

    chips.removeAllViews()
    if (state.presetsFailed) return
    val enabled = state.replyTo != null && !state.sending
    val inflater = LayoutInflater.from(chips.context)
    for (preset in state.presets) {
        val chip = inflater.inflate(R.layout.item_reply_chip, chips, false) as Chip
        chip.text = preset.label
        chip.isEnabled = enabled
        chip.setOnClickListener { onPreset(preset.code) }
        chips.addView(chip)
    }
}
