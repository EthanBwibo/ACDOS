package com.kq.acdos.ui.crew

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.data.MessagesRepository
import com.kq.acdos.data.local.CrewDao
import com.kq.acdos.data.local.PresetMessageEntity
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.data.remote.ErrorCode
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** What the crew member is told after tapping a preset. */
@StringRes
fun sendMessage(result: ApiResult<*>): Int = when (result) {
    is ApiResult.Success -> R.string.crew_message_sent

    is ApiResult.NetworkError -> R.string.crew_message_offline

    is ApiResult.Error -> if (result.code == ErrorCode.UNAUTHORIZED) {
        R.string.crew_refresh_sign_in_again
    } else {
        R.string.crew_message_failed
    }
}

/** One row of RECENT: something the crew member sent, or the dispatcher's reply. */
sealed interface RecentRow {
    val at: Instant

    data class Sent(val message: CrewMessageDto) : RecentRow {
        override val at: Instant get() = message.sentAt
    }

    data class Reply(val label: String, override val at: Instant) : RecentRow
}

/** Messages and replies in one list, newest first, no longer than the list on screen. */
fun recentRows(messages: List<CrewMessageDto>): List<RecentRow> = messages
    .flatMap { message ->
        val replies = message.replies.map { RecentRow.Reply(it.label, it.sentAt) }
        listOf(RecentRow.Sent(message)) + replies
    }
    .sortedByDescending { it.at }
    .take(MessagesRepository.RECENT_SIZE)

/**
 * The Message tab (#57): the cached presets, refreshed when the tab opens,
 * and sending one. [repository] is null without an API URL.
 */
class CrewMessageViewModel(
    dao: CrewDao,
    private val repository: MessagesRepository?,
    private val newKey: () -> String = { UUID.randomUUID().toString() }
) : ViewModel() {
    val presets: StateFlow<List<PresetMessageEntity>> = dao.observePresets()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    private val sendingState = MutableStateFlow(false)

    /** True while a message is on its way, so the buttons can't send a second one. */
    val sending: StateFlow<Boolean> = sendingState.asStateFlow()

    private val messageChannel = Channel<Int>(Channel.BUFFERED)

    /** String resources to show once each. */
    val messages: Flow<Int> = messageChannel.receiveAsFlow()

    /**
     * One key per preset until it is sent: tapping it again after a failure
     * retries the same message, so a send that did get through isn't doubled.
     */
    private val pendingKeys = mutableMapOf<String, String>()

    private val recentState = MutableStateFlow<List<CrewMessageDto>>(emptyList())

    /** The crew member's own latest messages, newest first. */
    val recent: StateFlow<List<CrewMessageDto>> = recentState.asStateFlow()

    fun refresh() {
        val repository = repository ?: return
        // Quiet on failure: the cached presets and the messages already shown stay.
        viewModelScope.launch { repository.refreshPresets() }
        viewModelScope.launch {
            (repository.recent() as? ApiResult.Success)?.let { recentState.value = it.body }
        }
    }

    fun send(presetCode: String) {
        val repository = repository ?: return
        if (sendingState.value) return
        sendingState.value = true
        val key = pendingKeys.getOrPut(presetCode, newKey)
        viewModelScope.launch {
            try {
                val result = repository.send(presetCode, key)
                if (result !is ApiResult.NetworkError) pendingKeys.remove(presetCode)
                if (result is ApiResult.Success) addToRecent(result.body)
                messageChannel.send(sendMessage(result))
            } finally {
                sendingState.value = false
            }
        }
    }

    /** A retry returns the message already sent, so it replaces rather than repeats. */
    private fun addToRecent(message: CrewMessageDto) {
        recentState.update { messages ->
            (listOf(message) + messages.filter { it.id != message.id })
                .take(MessagesRepository.RECENT_SIZE)
        }
    }

    companion object {
        val Factory: ViewModelProvider.Factory = viewModelFactory {
            initializer {
                val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY]
                val container = (app as AcdosApplication).container
                CrewMessageViewModel(container.database.crewDao(), container.messagesRepository)
            }
        }
    }
}
