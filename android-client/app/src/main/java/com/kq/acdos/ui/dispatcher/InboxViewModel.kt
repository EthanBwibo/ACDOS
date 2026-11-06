package com.kq.acdos.ui.dispatcher

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.kq.acdos.AcdosApplication
import com.kq.acdos.data.MessagesRepository
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.CrewMessageDto
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * The dispatcher's inbox of crew messages (#57), newest first. Loaded when
 * the screen opens and on Refresh; a failed load keeps the list as it was.
 * [repository] is null without an API URL.
 */
class InboxViewModel(private val repository: MessagesRepository?) : ViewModel() {
    private val inbox = MutableStateFlow<List<CrewMessageDto>?>(null)

    /** Null until the first load answers. */
    val messages: StateFlow<List<CrewMessageDto>?> = inbox.asStateFlow()

    init {
        load()
    }

    fun load() {
        val repository = repository ?: return
        viewModelScope.launch {
            val result = repository.inbox()
            if (result is ApiResult.Success) inbox.value = result.body
        }
    }

    /** Quiet on failure: the message stays unread, and the next tap tries again. */
    fun markRead(messageId: String) {
        val repository = repository ?: return
        viewModelScope.launch {
            val result = repository.markRead(messageId)
            if (result is ApiResult.Success) {
                inbox.update { messages ->
                    messages?.map {
                        if (it.id == messageId) it.copy(readAt = result.body.readAt) else it
                    }
                }
            }
        }
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
