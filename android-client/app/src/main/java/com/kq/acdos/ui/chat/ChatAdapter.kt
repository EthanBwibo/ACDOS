package com.kq.acdos.ui.chat

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.card.MaterialCardView
import com.kq.acdos.R
import com.kq.acdos.ui.Times
import java.time.Instant

/**
 * The conversation on crew Message and dispatcher Messages (#226). Lines the
 * viewer sent are on the right in the primary container colour; the other
 * side's are on the left. On the dispatcher's screen a left bubble carries the
 * crew member's name, and tapping it picks the message to reply to.
 */
class ChatAdapter(
    private val onCrewMessageTap: ((ChatItem.Bubble) -> Unit)? = null,
    private val now: () -> Instant = Instant::now
) : ListAdapter<ChatItem, RecyclerView.ViewHolder>(Diff) {

    /** The crew message the dispatcher is replying to, outlined. */
    var selectedMessageId: String? = null
        set(value) {
            if (field == value) return
            field = value
            notifyItemRangeChanged(0, itemCount)
        }

    override fun getItemViewType(position: Int): Int = when (val item = getItem(position)) {
        is ChatItem.Day -> TYPE_DAY
        is ChatItem.Bubble -> if (item.mine) TYPE_MINE else TYPE_THEIRS
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
        val layout = when (viewType) {
            TYPE_DAY -> R.layout.item_chat_day
            TYPE_MINE -> R.layout.item_chat_mine
            else -> R.layout.item_chat_theirs
        }
        val view = LayoutInflater.from(parent.context).inflate(layout, parent, false)
        return if (viewType == TYPE_DAY) DayHolder(view) else BubbleHolder(view)
    }

    override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
        when (val item = getItem(position)) {
            is ChatItem.Day -> (holder as DayHolder).bind(item)
            is ChatItem.Bubble -> (holder as BubbleHolder).bind(item)
        }
    }

    private inner class DayHolder(view: View) : RecyclerView.ViewHolder(view) {
        private val label = view as TextView

        fun bind(item: ChatItem.Day) {
            label.text = if (item.date == Times.date(now())) {
                label.context.getString(R.string.chat_today)
            } else {
                Times.day(item.date)
            }
        }
    }

    private inner class BubbleHolder(view: View) : RecyclerView.ViewHolder(view) {
        private val card = view.findViewById<MaterialCardView>(R.id.bubble)
        private val text = view.findViewById<TextView>(R.id.bubble_text)
        private val meta = view.findViewById<TextView>(R.id.bubble_meta)
        private val senderName: TextView? = view.findViewById(R.id.bubble_sender)
        private val selectedStroke =
            view.resources.getDimensionPixelSize(R.dimen.chat_selected_stroke)

        fun bind(item: ChatItem.Bubble) {
            val context = itemView.context
            text.text = item.text
            val clock = Times.shortClock(item.at)
            meta.text = when {
                item.sender != Sender.CREW -> clock
                item.mine && item.readAt != null -> context.getString(R.string.chat_seen, clock)
                item.mine -> context.getString(R.string.chat_sent, clock)
                item.readAt == null -> context.getString(R.string.chat_new, clock)
                else -> clock
            }
            // Only the dispatcher sees crew messages on the left, and needs to know whose.
            val showName = !item.mine && item.sender == Sender.CREW
            senderName?.isVisible = showName
            senderName?.text = item.crewName

            val onTap = onCrewMessageTap.takeIf { showName }
            if (onTap == null) {
                card.setOnClickListener(null)
                card.isClickable = false
            } else {
                card.setOnClickListener { onTap(item) }
            }
            val selected = onTap != null && item.messageId == selectedMessageId
            card.strokeWidth = if (selected) selectedStroke else 0
        }
    }

    private object Diff : DiffUtil.ItemCallback<ChatItem>() {
        override fun areItemsTheSame(old: ChatItem, new: ChatItem): Boolean = when {
            old is ChatItem.Day && new is ChatItem.Day -> old.date == new.date
            old is ChatItem.Bubble && new is ChatItem.Bubble -> old.key == new.key
            else -> false
        }

        override fun areContentsTheSame(old: ChatItem, new: ChatItem): Boolean = old == new
    }

    companion object {
        const val TYPE_DAY = 0
        const val TYPE_MINE = 1
        const val TYPE_THEIRS = 2
    }
}
