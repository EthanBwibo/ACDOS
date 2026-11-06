package com.kq.acdos.ui.dispatcher

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.data.DayBoard
import com.kq.acdos.data.DispatchRepository
import com.kq.acdos.data.PlanSummary
import com.kq.acdos.data.planSummary
import com.kq.acdos.data.plannableVans
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.DispatcherPickupDto
import com.kq.acdos.data.remote.DispatcherVehicleDto
import com.kq.acdos.data.remote.ErrorCode
import com.kq.acdos.data.remote.OptimizationJobStatusDto
import com.kq.acdos.data.remote.OptimizationTriggerTypeDto
import com.kq.acdos.data.remote.VehicleStatusDto
import com.kq.acdos.data.strandedPickups
import com.kq.acdos.data.unplannedPickups
import com.kq.acdos.ui.Times
import java.time.Instant
import java.time.LocalDate
import kotlin.time.Duration
import kotlin.time.Duration.Companion.seconds
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * A disruption recorded but not re-planned yet. Neither PATCH re-plans, so
 * the dispatcher re-plans with an explicit tap.
 */
data class PendingReplan(
    val trigger: OptimizationTriggerTypeDto,
    val pickupIds: List<String>,
    /** "Flight delay for %1$s", with [subject] for %1$s. */
    @StringRes val label: Int,
    val subject: String
)

/** The latest optimisation job started from this screen. */
sealed interface JobUi {
    /** True until the job ends, so a second one can't be started on top of it. */
    val isActive: Boolean get() = this == Queued || this == Running

    data object None : JobUi

    data object Queued : JobUi

    data object Running : JobUi

    data class Done(val routes: Int, val late: Int, val unassigned: Int) : JobUi

    data class Failed(val error: String?) : JobUi
}

data class DispatcherUiState(
    /** A Nairobi day. */
    val date: LocalDate,
    val board: DayBoard? = null,
    val loading: Boolean = false,
    val job: JobUi = JobUi.None,
    val replan: PendingReplan? = null,
    /** The plan as it was when the latest job started, for Re-plan's Before and After. */
    val before: PlanSummary? = null,
    /** Why the last load failed, null once one works. The last board stays on screen. */
    val loadFailure: DispatcherMessage? = null
)

/** A Snackbar: [text], with the server's [detail] for %1$s when there is one. */
data class DispatcherMessage(@StringRes val text: Int, val detail: String? = null)

/** What the dispatcher is told when a call fails. */
fun failureMessage(failure: ApiResult<Nothing>): DispatcherMessage = when (failure) {
    is ApiResult.NetworkError -> DispatcherMessage(R.string.dispatch_offline)

    is ApiResult.Error -> if (failure.code == ErrorCode.FORBIDDEN) {
        DispatcherMessage(R.string.dispatch_not_allowed)
    } else {
        // The detail names what went wrong, e.g. which route has already left.
        DispatcherMessage(R.string.dispatch_failed, failure.body?.detail ?: "${failure.status}")
    }

    // ApiResult<Nothing> can't hold a body, so a Success never arrives here.
    is ApiResult.Success -> error("not a failure")
}

/** What the dispatcher is told when the day can't load, until a load works. */
fun loadFailureMessage(failure: ApiResult<Nothing>): DispatcherMessage = when (failure) {
    is ApiResult.NetworkError -> DispatcherMessage(R.string.dispatch_load_offline)

    is ApiResult.Error -> if (failure.code == ErrorCode.FORBIDDEN) {
        DispatcherMessage(R.string.dispatch_not_allowed)
    } else {
        val detail = failure.body?.detail ?: "${failure.status}"
        DispatcherMessage(R.string.dispatch_load_failed, detail)
    }

    is ApiResult.Success -> error("not a failure")
}

/**
 * The dispatcher's day: load it, run a first plan, record a flight delay or a
 * breakdown, then re-plan. [repository] is null in builds without an API URL.
 */
class DispatcherViewModel(
    private val repository: DispatchRepository?,
    today: LocalDate,
    private val pollEvery: Duration = 2.seconds,
    /** 3 minutes at 2 s, the solver's worst case with room to spare. */
    private val maxPolls: Int = 90
) : ViewModel() {
    private val uiState = MutableStateFlow(DispatcherUiState(today))
    val state: StateFlow<DispatcherUiState> = uiState.asStateFlow()

    private val messageChannel = Channel<DispatcherMessage>(Channel.BUFFERED)
    val messages: Flow<DispatcherMessage> = messageChannel.receiveAsFlow()

    init {
        load()
    }

    /** [days] is -1 for the day before, +1 for the day after. */
    fun showDay(days: Long) {
        uiState.update { it.copy(date = it.date.plusDays(days), board = null) }
        load()
    }

    fun load() {
        val repository = repository ?: return
        val date = uiState.value.date
        uiState.update { it.copy(loading = true) }
        viewModelScope.launch {
            when (val result = repository.loadDay(date)) {
                // The dispatcher may have moved to another day meanwhile.
                is ApiResult.Success -> uiState.update {
                    if (it.date == date) it.copy(board = result.body, loadFailure = null) else it
                }

                is ApiResult.Error -> failLoad(result)

                is ApiResult.NetworkError -> failLoad(result)
            }
            uiState.update { it.copy(loading = false) }
        }
    }

    private fun failLoad(failure: ApiResult<Nothing>) =
        uiState.update { it.copy(loadFailure = loadFailureMessage(failure)) }

    /**
     * A first plan for the day's pickups not on a route yet. [vehicleIds] are the
     * vans ticked in the picker; by default every plannable one.
     */
    fun runOptimisation(vehicleIds: List<String>? = null) {
        val board = uiState.value.board ?: return
        startJob(OptimizationTriggerTypeDto.SCHEDULED, unplannedPickups(board), vehicleIds)
    }

    fun delayFlight(pickup: DispatcherPickupDto, reportTime: Instant) {
        val repository = repository ?: return
        viewModelScope.launch {
            when (val result = repository.delayFlight(pickup.id, reportTime)) {
                is ApiResult.Success -> {
                    val replan = PendingReplan(
                        OptimizationTriggerTypeDto.FLIGHT_DELAY,
                        listOf(pickup.id),
                        R.string.dispatch_replan_flight_delay,
                        pickup.crewName
                    )
                    uiState.update { it.copy(replan = replan) }
                    load()
                }

                is ApiResult.Error -> report(result)

                is ApiResult.NetworkError -> report(result)
            }
        }
    }

    fun markBrokenDown(vehicle: DispatcherVehicleDto) {
        val board = uiState.value.board ?: return
        // Read before the PATCH: the board still shows the van's route.
        val stranded = strandedPickups(board, vehicle.id)
        setVehicleStatus(vehicle, VehicleStatusDto.BROKEN_DOWN) {
            if (stranded.isNotEmpty()) {
                PendingReplan(
                    OptimizationTriggerTypeDto.VEHICLE_BREAKDOWN,
                    stranded,
                    R.string.dispatch_replan_breakdown,
                    vehicle.plateNumber
                )
            } else {
                null
            }
        }
    }

    /** Back in service after a breakdown, e.g. to run the demo again. */
    fun markAvailable(vehicle: DispatcherVehicleDto) =
        setVehicleStatus(vehicle, VehicleStatusDto.AVAILABLE) { uiState.value.replan }

    /** Runs the job for the recorded disruption, with the ticked vans as for [runOptimisation]. */
    fun replan(vehicleIds: List<String>? = null) {
        val replan = uiState.value.replan ?: return
        startJob(replan.trigger, replan.pickupIds, vehicleIds)
    }

    /** Drops the alert. What was recorded stays recorded: only the re-plan is skipped. */
    fun discardReplan() = uiState.update { it.copy(replan = null) }

    private fun setVehicleStatus(
        vehicle: DispatcherVehicleDto,
        status: VehicleStatusDto,
        replanAfter: () -> PendingReplan?
    ) {
        val repository = repository ?: return
        viewModelScope.launch {
            when (val result = repository.setVehicleStatus(vehicle.id, status)) {
                is ApiResult.Success -> {
                    uiState.update { it.copy(replan = replanAfter()) }
                    load()
                }

                is ApiResult.Error -> report(result)

                is ApiResult.NetworkError -> report(result)
            }
        }
    }

    private fun startJob(
        trigger: OptimizationTriggerTypeDto,
        pickupIds: List<String>,
        vehicleIds: List<String>?
    ) {
        val repository = repository ?: return
        val board = uiState.value.board ?: return
        // Only plannable vans, even if the board changed while the picker was open.
        val vans = plannableVans(board).filter { vehicleIds == null || it in vehicleIds }
        when {
            pickupIds.isEmpty() -> send(DispatcherMessage(R.string.dispatch_nothing_to_plan))

            vans.isEmpty() -> send(DispatcherMessage(R.string.dispatch_no_free_vans))

            else -> viewModelScope.launch {
                when (val result = repository.startJob(trigger, pickupIds, vans)) {
                    is ApiResult.Success -> {
                        val replan = uiState.value.replan
                        uiState.update {
                            it.copy(replan = null, job = JobUi.Queued, before = planSummary(board))
                        }
                        follow(repository, result.body.id, replan)
                    }

                    is ApiResult.Error -> report(result)

                    is ApiResult.NetworkError -> report(result)
                }
            }
        }
    }

    /**
     * Polls the job until it ends, then reloads the day to show the new routes.
     * If it fails, [replan] comes back, or a van left broken down would have no
     * alert to re-plan from.
     */
    private suspend fun follow(
        repository: DispatchRepository,
        jobId: String,
        replan: PendingReplan?
    ) {
        repeat(maxPolls) {
            delay(pollEvery)
            when (val result = repository.job(jobId)) {
                is ApiResult.Success -> {
                    val job = result.body
                    when (job.status) {
                        OptimizationJobStatusDto.QUEUED -> Unit

                        OptimizationJobStatusDto.RUNNING ->
                            uiState.update { it.copy(job = JobUi.Running) }

                        OptimizationJobStatusDto.COMPLETED -> {
                            val done =
                                JobUi.Done(job.routes.size, job.late.size, job.unassigned.size)
                            uiState.update { it.copy(job = done) }
                            load()
                            return
                        }

                        OptimizationJobStatusDto.FAILED -> {
                            uiState.update {
                                it.copy(job = JobUi.Failed(job.error), replan = replan)
                            }
                            return
                        }
                    }
                }

                // A dropped poll on a weak signal: the job carries on, so ask again.
                is ApiResult.NetworkError -> Unit

                is ApiResult.Error -> {
                    uiState.update { it.copy(job = JobUi.None, replan = replan) }
                    report(result)
                    return
                }
            }
        }
        uiState.update { it.copy(job = JobUi.Failed(null), replan = replan) }
    }

    private fun report(failure: ApiResult<Nothing>) = send(failureMessage(failure))

    private fun send(message: DispatcherMessage) {
        messageChannel.trySend(message)
    }

    companion object {
        val Factory: ViewModelProvider.Factory = viewModelFactory {
            initializer {
                val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY]
                val container = (app as AcdosApplication).container
                DispatcherViewModel(container.dispatchRepository, LocalDate.now(Times.ZONE))
            }
        }
    }
}
