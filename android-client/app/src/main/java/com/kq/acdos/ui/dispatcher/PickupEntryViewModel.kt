package com.kq.acdos.ui.dispatcher

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.data.PickupEntryRepository
import com.kq.acdos.data.remote.ApiResult
import com.kq.acdos.data.remote.CrewHomeDto
import com.kq.acdos.data.remote.CrewListItemDto
import com.kq.acdos.data.remote.DispatcherPickupDto
import com.kq.acdos.data.remote.ErrorCode
import com.kq.acdos.data.remote.LatLonDto
import com.kq.acdos.data.remote.NearestZoneDto
import com.kq.acdos.data.remote.PickupRequestCreateDto
import com.kq.acdos.data.remote.PickupRequestTypeDto
import java.time.Instant
import java.util.Locale
import java.util.UUID
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The Crew list under Fleet & crew (#253): one search, then pages of 20. */
data class CrewListState(
    val query: String = "",
    val items: List<CrewListItemDto> = emptyList(),
    val nextCursor: String? = null,
    val loading: Boolean = false,
    val failure: DispatcherMessage? = null,
    /** False until the first page answers. */
    val loaded: Boolean = false
)

/** A pin on the map and what the server says about it. */
data class PinState(
    val point: LatLonDto? = null,
    /** The nearest-zone request for [point] is out. */
    val checking: Boolean = false,
    val nearest: NearestZoneDto? = null,
    val failure: DispatcherMessage? = null
) {
    /** Only a pin the server has placed within the zones can be used. */
    val usable: Boolean get() = point != null && nearest?.withinPickupZones == true && !checking
}

/** Where an added pickup starts: the crew member's home, or a pin on the map. */
sealed interface PickupPlace {
    data object Home : PickupPlace

    data class Pin(val point: LatLonDto, val nearest: NearestZoneDto) : PickupPlace
}

/** The Add pickup form (#253). */
data class AddPickupState(
    val query: String = "",
    val results: List<CrewListItemDto> = emptyList(),
    val searching: Boolean = false,
    val crew: CrewListItemDto? = null,
    /** Nairobi date and time, as one instant. */
    val reportTime: Instant? = null,
    val type: PickupRequestTypeDto = PickupRequestTypeDto.ROSTERED,
    val place: PickupPlace = PickupPlace.Home,
    val busy: Boolean = false,
    val failure: DispatcherMessage? = null,
    /** The pickup the server made; the form is done. */
    val added: DispatcherPickupDto? = null
) {
    /** Every crew member has a home, and a pin is only kept once the server placed it in range. */
    val canSave: Boolean
        get() = crew != null && reportTime != null && !busy && added == null
}

/** Set home for the crew member on the Crew detail screen. */
data class SetHomeState(
    val busy: Boolean = false,
    val failure: DispatcherMessage? = null,
    val saved: CrewHomeDto? = null
)

/**
 * The Crew list and detail, Add pickup and Set home (#253), shared by their screens.
 * [repository] is null in builds without an API URL. No write here re-plans.
 */
class PickupEntryViewModel(
    private val repository: PickupEntryRepository?,
    private val newKey: () -> String = { UUID.randomUUID().toString() },
    private val searchDelayMs: Long = SEARCH_DELAY_MS
) : ViewModel() {
    private val crewState = MutableStateFlow(CrewListState())
    val crewList: StateFlow<CrewListState> = crewState.asStateFlow()

    private val detail = MutableStateFlow<CrewListItemDto?>(null)

    /** The crew member on the Crew detail screen. */
    val crewDetail: StateFlow<CrewListItemDto?> = detail.asStateFlow()

    private val form = MutableStateFlow(AddPickupState())
    val addPickup: StateFlow<AddPickupState> = form.asStateFlow()

    private val pinState = MutableStateFlow(PinState())
    val pin: StateFlow<PinState> = pinState.asStateFlow()

    private val home = MutableStateFlow(SetHomeState())
    val setHome: StateFlow<SetHomeState> = home.asStateFlow()

    /**
     * One key per form as it stands: a retry of the same Save after no answer sends the
     * same key and body, so a pickup that did get through isn't added twice. Any change
     * to the form is a different pickup, so it drops the key.
     */
    private var key: String? = null

    private var crewSearch: Job? = null
    private var formSearch: Job? = null
    private var pinCheck: Job? = null

    // The Crew list.

    /** Waits for a pause in typing, so each key press isn't a request. */
    fun searchCrewList(query: String) {
        if (crewState.value.loaded && query == crewState.value.query) return
        crewState.update { it.copy(query = query) }
        crewSearch?.cancel()
        val repository = repository ?: return
        crewSearch = viewModelScope.launch {
            if (query.isNotEmpty()) delay(searchDelayMs)
            crewState.update { it.copy(loading = true, failure = null) }
            val result = repository.crew(query.trim())
            crewState.update {
                when (result) {
                    is ApiResult.Success -> it.copy(
                        items = result.body.items,
                        nextCursor = result.body.nextCursor,
                        loading = false,
                        loaded = true
                    )

                    else -> it.copy(loading = false, failure = entryFailure(result.failure()))
                }
            }
        }
    }

    /** The first page, when the list opens. */
    fun loadCrewList() {
        if (!crewState.value.loaded && crewSearch?.isActive != true) searchCrewList("")
    }

    fun loadMoreCrew() {
        val repository = repository ?: return
        val state = crewState.value
        val cursor = state.nextCursor ?: return
        if (state.loading) return
        crewState.update { it.copy(loading = true, failure = null) }
        crewSearch = viewModelScope.launch {
            val result = repository.crew(state.query.trim(), cursor)
            crewState.update {
                when (result) {
                    is ApiResult.Success -> it.copy(
                        items = it.items + result.body.items,
                        nextCursor = result.body.nextCursor,
                        loading = false
                    )

                    else -> it.copy(loading = false, failure = entryFailure(result.failure()))
                }
            }
        }
    }

    fun openCrew(crew: CrewListItemDto) {
        detail.value = crew
        home.value = SetHomeState()
    }

    // Add pickup.

    /** A fresh form each time Add pickup opens. */
    fun startAddPickup() {
        formSearch?.cancel()
        key = null
        form.value = AddPickupState()
    }

    /** The same crew search as the list, first page only: a longer query narrows it. */
    fun search(query: String) {
        form.update { it.copy(query = query) }
        formSearch?.cancel()
        val text = query.trim()
        if (text.length < MIN_QUERY) {
            form.update { it.copy(results = emptyList(), searching = false) }
            return
        }
        val repository = repository ?: return
        formSearch = viewModelScope.launch {
            delay(searchDelayMs)
            form.update { it.copy(searching = true) }
            val result = repository.crew(text)
            form.update {
                when (result) {
                    is ApiResult.Success -> it.copy(results = result.body.items, searching = false)
                    else -> it.copy(searching = false, failure = entryFailure(result.failure()))
                }
            }
        }
    }

    fun chooseCrew(crew: CrewListItemDto?) = change { copy(crew = crew, results = emptyList()) }

    fun setReportTime(time: Instant) = change { copy(reportTime = time) }

    fun setType(type: PickupRequestTypeDto) = change { copy(type = type) }

    fun useHome() = change { copy(place = PickupPlace.Home) }

    /** The pin screen's point, once the server placed it within the zones. */
    fun usePin() {
        val pin = pinState.value
        val point = pin.point ?: return
        val nearest = pin.nearest ?: return
        if (pin.usable) change { copy(place = PickupPlace.Pin(point, nearest)) }
    }

    private fun change(update: AddPickupState.() -> AddPickupState) {
        key = null
        form.update { it.update().copy(failure = null) }
    }

    fun save() {
        val state = form.value
        val repository = repository ?: return
        val crew = state.crew ?: return
        val reportTime = state.reportTime ?: return
        if (!state.canSave) return
        val sending = key ?: newKey().also { key = it }
        val body = PickupRequestCreateDto(
            crewMemberId = crew.id,
            reportTime = reportTime,
            requestType = state.type,
            pickupLocation = (state.place as? PickupPlace.Pin)?.point
        )
        form.update { it.copy(busy = true, failure = null) }
        viewModelScope.launch {
            val result = repository.addPickup(body, sending)
            form.update {
                when (result) {
                    is ApiResult.Success -> it.copy(busy = false, added = result.body)
                    else -> it.copy(busy = false, failure = entryFailure(result.failure()))
                }
            }
        }
    }

    // The map pin, for Add pickup and Set home.

    /** A fresh pin screen: no point yet. */
    fun startPin() {
        pinCheck?.cancel()
        pinState.value = PinState()
    }

    /**
     * The pin was dropped at [point]: one nearest-zone request. A newer drop cancels
     * an older request still out, so the answer on screen is always for this pin.
     */
    fun placePin(point: LatLonDto) {
        pinCheck?.cancel()
        pinState.value = PinState(point = point, checking = repository != null)
        val repository = repository ?: return
        pinCheck = viewModelScope.launch {
            val result = repository.nearestZone(point)
            pinState.update {
                when (result) {
                    is ApiResult.Success -> it.copy(checking = false, nearest = result.body)
                    else -> it.copy(checking = false, failure = entryFailure(result.failure()))
                }
            }
        }
    }

    // Set home.

    /** Only a pin the server placed within the zones is sent; the PATCH checks it again. */
    fun saveHome() {
        val repository = repository ?: return
        val crew = detail.value ?: return
        val point = pinState.value.point ?: return
        if (!pinState.value.usable || home.value.busy) return
        home.value = SetHomeState(busy = true)
        viewModelScope.launch {
            val result = repository.setHome(crew.id, point)
            if (result is ApiResult.Success) moved(crew.id, result.body)
            home.value = when (result) {
                is ApiResult.Success -> SetHomeState(saved = result.body)
                else -> SetHomeState(failure = entryFailure(result.failure()))
            }
        }
    }

    /** The detail screen and the list show the new home without another load. */
    private fun moved(crewMemberId: String, saved: CrewHomeDto) {
        val update: (CrewListItemDto) -> CrewListItemDto = {
            if (it.id ==
                crewMemberId
            ) {
                it.copy(home = saved.home, homeZoneLabel = saved.zoneLabel)
            } else {
                it
            }
        }
        detail.update { it?.let(update) }
        crewState.update { it.copy(items = it.items.map(update)) }
    }

    companion object {
        /** Fewer letters would match most of the roster. */
        const val MIN_QUERY = 2
        const val SEARCH_DELAY_MS = 300L

        val Factory: ViewModelProvider.Factory = viewModelFactory {
            initializer {
                val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY]
                PickupEntryViewModel((app as AcdosApplication).container.pickupEntryRepository)
            }
        }
    }
}

/** A failed call as the ApiResult<Nothing> the failure messages read. */
private fun ApiResult<*>.failure(): ApiResult<Nothing> = when (this) {
    is ApiResult.Error -> this
    is ApiResult.NetworkError -> this
    is ApiResult.Success -> ApiResult.Error(status = null, body = null)
}

/** The roster import's reasons, which Add pickup and Set home answer with as error codes. */
@StringRes
internal fun entryReason(code: ErrorCode): Int? = when (code) {
    ErrorCode.OUTSIDE_PICKUP_ZONES -> R.string.roster_reason_outside_zones
    ErrorCode.REPORT_TIME_PAST -> R.string.roster_reason_report_time_past
    ErrorCode.DUPLICATE_PICKUP -> R.string.roster_reason_duplicate
    else -> null
}

/** In the import's words when it's one of its reasons, otherwise as any other failure. */
internal fun entryFailure(failure: ApiResult<Nothing>): DispatcherMessage =
    (failure as? ApiResult.Error)?.code?.let(::entryReason)?.let { DispatcherMessage(it) }
        ?: failureMessage(failure)

/** "2.3", for the km in "Nearest zone: Westlands · 2.3 km". */
internal fun kmText(nearest: NearestZoneDto): String = "%.1f".format(Locale.UK, nearest.distanceKm)

/** The pin's line under the map, for a pin the server has placed. */
@StringRes
internal fun pinPreviewText(nearest: NearestZoneDto): Int =
    if (nearest.withinPickupZones) R.string.pin_nearest_zone else R.string.pin_too_far
