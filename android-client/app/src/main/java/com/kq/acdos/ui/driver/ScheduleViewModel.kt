package com.kq.acdos.ui.driver

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.data.DriverScheduleRepository
import com.kq.acdos.data.RefreshResult
import com.kq.acdos.data.ScheduleResult
import com.kq.acdos.data.remote.RouteSummaryDto
import com.kq.acdos.ui.Times
import java.time.Instant
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ScheduleRow(
    val plate: String,
    val firstPickup: Instant,
    val crewCount: Int,
    /** The first pickup's time has passed. */
    val started: Boolean,
    /** False for today's routes, whose section already says the day. */
    val showDay: Boolean
)

data class ScheduleSections(val today: List<ScheduleRow>, val upcoming: List<ScheduleRow>) {
    val isEmpty get() = today.isEmpty() && upcoming.isEmpty()
}

/**
 * Today and later, by Nairobi date. A route still active from an earlier day goes under
 * Today, because it is what the driver has to deal with now, and it keeps its date so it
 * can't pass for today's.
 */
fun scheduleSections(routes: List<RouteSummaryDto>, now: Instant): ScheduleSections {
    val today = Times.date(now)
    val rows = routes.sortedBy { it.firstPickup }.map {
        ScheduleRow(
            plate = it.vehiclePlate,
            firstPickup = it.firstPickup,
            crewCount = it.stopCount,
            started = it.firstPickup <= now,
            showDay = Times.date(it.firstPickup) != today
        )
    }
    val (current, later) = rows.partition { !Times.date(it.firstPickup).isAfter(today) }
    return ScheduleSections(today = current, upcoming = later)
}

data class ScheduleUiState(
    val loading: Boolean = false,
    /** Null until the first answer. Stays on screen if a later refresh fails. */
    val sections: ScheduleSections? = null,
    @StringRes val error: Int? = null
)

@StringRes
fun scheduleError(reason: RefreshResult): Int = when (reason) {
    RefreshResult.SIGN_IN_AGAIN -> R.string.route_refresh_sign_in_again
    RefreshResult.NOT_ALLOWED -> R.string.route_refresh_not_allowed
    else -> R.string.schedule_load_failed
}

/** Lives as long as the driver home, so going back to Schedule doesn't refetch on 2G. */
class ScheduleViewModel(
    private val repository: DriverScheduleRepository?,
    private val clock: () -> Instant = Instant::now
) : ViewModel() {
    private val stateFlow = MutableStateFlow(ScheduleUiState())
    val state: StateFlow<ScheduleUiState> = stateFlow.asStateFlow()

    /** On opening the tab: only if nothing has loaded yet, which also retries a failure. */
    fun loadIfNeeded() {
        if (stateFlow.value.sections == null) load()
    }

    fun load() {
        val repository = repository
        if (repository == null) {
            stateFlow.value = ScheduleUiState(sections = ScheduleSections(emptyList(), emptyList()))
            return
        }
        if (stateFlow.value.loading) return
        stateFlow.update { it.copy(loading = true) }
        viewModelScope.launch {
            val answer = repository.routes()
            stateFlow.update { state ->
                when (answer) {
                    is ScheduleResult.Loaded -> ScheduleUiState(
                        sections = scheduleSections(answer.routes, clock())
                    )

                    is ScheduleResult.Failed -> state.copy(
                        loading = false,
                        error = scheduleError(answer.reason)
                    )
                }
            }
        }
    }

    companion object {
        val Factory: ViewModelProvider.Factory = viewModelFactory {
            initializer {
                val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY]
                ScheduleViewModel((app as AcdosApplication).container.driverScheduleRepository)
            }
        }
    }
}
