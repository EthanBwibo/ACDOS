package com.kq.acdos.ui.dispatcher

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.data.MessagesRepository
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.data.remote.MessageReplyDto
import com.kq.acdos.data.remote.PresetMessageDto
import java.util.UUID
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** What the dispatcher is told after tapping a reply. */
@StringRes
fun replyMessage(result: ApiResult<*>): Int = when (result) {
    is ApiResult.Success -> R.string.dispatch_reply_sent
    is ApiResult.NetworkError -> R.string.dispatch_reply_offline
    is ApiResult.Error -> R.string.dispatch_reply_failed
}

/**
 * The dispatcher's inbox of crew messages (#57), newest first, and preset
 * replies to them. Loaded when the screen opens and on Refresh; a failed load
 * keeps the list as it was. [repository] is null without an API URL.
 */
class InboxViewModel(
    private val repository: MessagesRepository?,
    private val newKey: () -> String = { UUID.randomUUID().toString() }
) : ViewModel() {
    private val inbox = MutableStateFlow<List<CrewMessageDto>?>(null)

    /** Null until the first load answers. */
    val messages: StateFlow<List<CrewMessageDto>?> = inbox.asStateFlow()

    private val selectedId = MutableStateFlow<String?>(null)

    /** The message a reply goes to. */
    val selected: StateFlow<String?> = selectedId.asStateFlow()

    private val presets = MutableStateFlow<List<PresetMessageDto>>(emptyList())

    /** The dispatcher's fixed replies. */
    val replyPresets: StateFlow<List<PresetMessageDto>> = presets.asStateFlow()

    private val replyingState = MutableStateFlow(false)

    /** True while a reply is on its way, so the chips can't send a second one. */
    val replying: StateFlow<Boolean> = replyingState.asStateFlow()

    private val noticeChannel = Channel<Int>(Channel.BUFFERED)

    /** String resources to show once each. */
    val notices: Flow<Int> = noticeChannel.receiveAsFlow()

    /**
     * One key per message and preset until it is sent: tapping it again after
     * a failure retries the same reply, so one that did get through isn't doubled.
     */
    private val pendingKeys = mutableMapOf<Pair<String, String>, String>()

    private val loadingState = MutableStateFlow(false)

    /** True while the inbox is on its way. */
    val loading: StateFlow<Boolean> = loadingState.asStateFlow()

    private val failedState = MutableStateFlow(false)

    /** True when the last load failed. The list as it was stays on screen. */
    val loadFailed: StateFlow<Boolean> = failedState.asStateFlow()

    init {
        load()
    }

    fun load() {
        val repository = repository ?: return
        loadingState.value = true
        viewModelScope.launch {
            val result = repository.inbox()
            if (result is ApiResult.Success) inbox.value = result.body
            failedState.value = result !is ApiResult.Success
            loadingState.value = false
        }
        viewModelScope.launch {
            val result = repository.replyPresets()
            if (result is ApiResult.Success) presets.value = result.body
        }
    }

    /** Opening a message marks it read, and replies then go to it. */
    fun select(messageId: String) {
        selectedId.value = messageId
        val unread = inbox.value.orEmpty().any { it.id == messageId && it.readAt == null }
        if (unread) markRead(messageId)
    }

    /** Quiet on failure: the message stays unread, and the next tap tries again. */
    private fun markRead(messageId: String) {
        val repository = repository ?: return
        viewModelScope.launch {
            val result = repository.markRead(messageId)
            if (result is ApiResult.Success) {
                change(messageId) { it.copy(readAt = it.readAt ?: result.body.readAt) }
            }
        }
    }

    fun reply(presetCode: String) {
        val repository = repository ?: return
        val messageId = selectedId.value ?: return
        if (replyingState.value) return
        replyingState.value = true
        val pending = messageId to presetCode
        val key = pendingKeys.getOrPut(pending, newKey)
        viewModelScope.launch {
            try {
                val result = repository.reply(messageId, presetCode, key)
                if (result !is ApiResult.NetworkError) pendingKeys.remove(pending)
                if (result is ApiResult.Success) addReply(messageId, result.body)
                noticeChannel.send(replyMessage(result))
            } finally {
                replyingState.value = false
            }
        }
    }

    /** The server marks a replied-to message read, so this copy does too. */
    private fun addReply(messageId: String, reply: MessageReplyDto) = change(messageId) { message ->
        message.copy(
            readAt = message.readAt ?: reply.sentAt,
            replies = message.replies.filter { it.id != reply.id } + reply
        )
    }

    private fun change(messageId: String, update: (CrewMessageDto) -> CrewMessageDto) {
        inbox.update { messages -> messages?.map { if (it.id == messageId) update(it) else it } }
    }

    companion object {
        val Factory: ViewModelProvider.Factory = viewModelFactory {
            initializer {
                val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY]
                InboxViewModel((app as AcdosApplication).container.messagesRepository)
            }
        }
    }
}
