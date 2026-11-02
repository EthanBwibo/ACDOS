package com.kq.acdos.ui.crew

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.data.CrewPickupRepository
import com.kq.acdos.data.RefreshResult
import com.kq.acdos.data.local.CrewDao
import com.kq.acdos.data.local.CrewPickupEntity
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

sealed interface CrewPickupState {
    /** Room hasn't answered yet: show nothing rather than "no pickup". */
    data object Loading : CrewPickupState

    data object NoPickup : CrewPickupState

    data class Pickup(val pickup: CrewPickupEntity) : CrewPickupState
}

/**
 * What the crew member is told after a refresh, or null for nothing. As on
 * the driver's Route tab: a refresh on start stays quiet when offline or
 * failing, since the "Updated" time shows how old the copy is.
 */
@StringRes
fun crewRefreshMessage(result: RefreshResult, manual: Boolean): Int? = when (result) {
    RefreshResult.SIGN_IN_AGAIN -> R.string.crew_refresh_sign_in_again
    RefreshResult.NOT_ALLOWED -> R.string.crew_refresh_not_allowed
    RefreshResult.OFFLINE -> if (manual) R.string.crew_refresh_offline else null
    RefreshResult.FAILED -> if (manual) R.string.crew_refresh_failed else null
    RefreshResult.UPDATED, RefreshResult.NO_ROUTE, RefreshResult.THROTTLED -> null
}

/** The cached pickup, and refreshes from the API. [repository] is null without an API URL. */
class CrewPickupViewModel(dao: CrewDao, private val repository: CrewPickupRepository?) :
    ViewModel() {
    val state: StateFlow<CrewPickupState> = dao.observePickup()
        .map { it?.let(CrewPickupState::Pickup) ?: CrewPickupState.NoPickup }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), CrewPickupState.Loading)

    private val refreshingState = MutableStateFlow(false)

    /** True while a pull to refresh is running, for the spinner. */
    val refreshing: StateFlow<Boolean> = refreshingState.asStateFlow()

    private val messageChannel = Channel<Int>(Channel.BUFFERED)

    /** String resources to show once each. */
    val messages: Flow<Int> = messageChannel.receiveAsFlow()

    /** False when there is nothing to refresh from, so the spinner can stop at once. */
    fun refresh(manual: Boolean): Boolean {
        val repository = repository ?: return false
        if (manual) refreshingState.value = true
        viewModelScope.launch {
            try {
                val result = repository.refresh()
                crewRefreshMessage(result, manual)?.let { messageChannel.send(it) }
            } finally {
                if (manual) refreshingState.value = false
            }
        }
        return true
    }

    companion object {
        val Factory: ViewModelProvider.Factory = viewModelFactory {
            initializer {
                val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY]
                val container = (app as AcdosApplication).container
                CrewPickupViewModel(container.database.crewDao(), container.crewPickupRepository)
            }
        }
    }
}
