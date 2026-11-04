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
import com.kq.acdos.data.remote.ErrorCode
import java.util.UUID
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
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

    fun refresh() {
        val repository = repository ?: return
        // Quiet on failure: the cached presets still show.
        viewModelScope.launch { repository.refreshPresets() }
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
                messageChannel.send(sendMessage(result))
            } finally {
                sendingState.value = false
            }
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
