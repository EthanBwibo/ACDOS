package com.kq.acdos.ui.driver

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.data.DriverRouteRepository
import com.kq.acdos.data.RefreshResult
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/**
 * What the driver is told after a refresh, or null for nothing. Automatic
 * refreshes stay quiet when offline or failing: the "Updated" time already
 * shows how old the route is. A session or role problem is always shown,
 * since refreshing again can't fix it.
 */
@StringRes
fun refreshMessage(result: RefreshResult, manual: Boolean): Int? = when (result) {
    RefreshResult.SIGN_IN_AGAIN -> R.string.route_refresh_sign_in_again

    RefreshResult.NOT_ALLOWED -> R.string.route_refresh_not_allowed

    RefreshResult.OFFLINE -> if (manual) R.string.route_refresh_offline else null

    RefreshResult.FAILED -> if (manual) R.string.route_refresh_failed else null

    RefreshResult.UPDATED, RefreshResult.NO_ROUTE, RefreshResult.THROTTLED -> null
}

/**
 * Shared by the driver home (refresh on start) and the Route tab (pull to
 * refresh), so it lives as long as the activity. [repository] is null in
 * builds without an API URL; then nothing refreshes.
 */
class RouteRefreshViewModel(private val repository: DriverRouteRepository?) : ViewModel() {
    private val refreshingState = MutableStateFlow(false)

    /** True while a pull to refresh is running, for the spinner. */
    val refreshing: StateFlow<Boolean> = refreshingState.asStateFlow()

    private val messageChannel = Channel<Int>(Channel.BUFFERED)

    /** String resources to show once each. */
    val messages: Flow<Int> = messageChannel.receiveAsFlow()

    /** [first]: the first start of the screen, forced past the throttle. */
    fun refreshOnStart(first: Boolean) {
        val repository = repository ?: return
        viewModelScope.launch {
            report(repository.refresh(force = first), manual = false)
        }
    }

    /** False when there is nothing to refresh from, so the spinner can stop at once. */
    fun refreshByPull(): Boolean {
        val repository = repository ?: return false
        refreshingState.value = true
        viewModelScope.launch {
            try {
                report(repository.refresh(force = true), manual = true)
            } finally {
                refreshingState.value = false
            }
        }
        return true
    }

    private suspend fun report(result: RefreshResult, manual: Boolean) {
        refreshMessage(result, manual)?.let { messageChannel.send(it) }
    }

    companion object {
        val Factory: ViewModelProvider.Factory = viewModelFactory {
            initializer {
                val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY]
                RouteRefreshViewModel((app as AcdosApplication).container.driverRouteRepository)
            }
        }
    }
}
