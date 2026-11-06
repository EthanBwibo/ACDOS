package com.kq.acdos.ui.driver

import androidx.annotation.StringRes
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.kq.acdos.R
import com.kq.acdos.data.local.PendingPickupEventEntity
import com.kq.acdos.data.local.PickupEventType
import com.kq.acdos.data.local.PickupExceptionType
import com.kq.acdos.data.local.RouteStopEntity
import java.time.Instant
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

enum class QueueStatus { WAITING, SENT, REFUSED }

/** One outbox event. The stop details are null once its route has left the phone. */
data class QueueRow(
    val key: String,
    @StringRes val action: Int,
    val zoneLabel: String?,
    val crewName: String?,
    val onBoard: Boolean,
    val at: Instant,
    val status: QueueStatus,
    /** The server's code when it refused the event. */
    val conflict: String?
)

data class SyncQueue(
    /** What goes next, in send order, then what has happened, newest first. */
    val rows: List<QueueRow>,
    val waiting: Int,
    val lastSynced: Instant?,
    /** Past events left off the end of [rows]. */
    val hidden: Int
)

/** The outbox never prunes, so the list stops at this many past events. */
const val QUEUE_HISTORY_ROWS = 20

@StringRes
private fun actionLabel(exception: PickupExceptionType?): Int = when (exception) {
    null -> R.string.sync_action_pickup
    PickupExceptionType.NO_SHOW -> R.string.route_status_no_show
    PickupExceptionType.VEHICLE_ISSUE -> R.string.route_problem_vehicle_issue
    PickupExceptionType.TRAFFIC_DELAY -> R.string.route_problem_traffic_delay
}

/** Why the server refused an event, from the code the outbox stored. */
@StringRes
fun refusalReason(code: String): Int = when (code) {
    "already_confirmed" -> R.string.sync_refused_already_confirmed
    "not_your_stop" -> R.string.sync_refused_not_your_stop
    else -> R.string.sync_refused_other
}

private fun PendingPickupEventEntity.status() = when {
    conflict != null -> QueueStatus.REFUSED
    syncedAt != null -> QueueStatus.SENT
    else -> QueueStatus.WAITING
}

/**
 * [events] is the outbox, oldest first, the order it uploads in. [stops] only names them: an
 * event outlives its stop, so a re-plan never removes it from this list.
 */
fun syncQueue(events: List<PendingPickupEventEntity>, stops: List<RouteStopEntity>): SyncQueue {
    val stopsById = stops.associateBy { it.routeNodeId }
    val rows = events.map { event ->
        val stop = stopsById[event.routeNodeId]
        QueueRow(
            key = event.idempotencyKey,
            action = actionLabel(event.exceptionType),
            zoneLabel = stop?.zoneLabel,
            crewName = stop?.crewName,
            onBoard = event.eventType == PickupEventType.PICKUP_CONFIRMED,
            at = event.confirmedAt,
            status = event.status(),
            conflict = event.conflict
        )
    }
    val (waiting, past) = rows.partition { it.status == QueueStatus.WAITING }
    return SyncQueue(
        rows = waiting + past.asReversed().take(QUEUE_HISTORY_ROWS),
        waiting = waiting.size,
        lastSynced = events.mapNotNull { it.syncedAt }.maxOrNull(),
        hidden = (past.size - QUEUE_HISTORY_ROWS).coerceAtLeast(0)
    )
}

/**
 * The Sync tab: the real outbox as Room holds it. [send] uploads what is waiting and returns
 * how many events are still waiting.
 */
class SyncViewModel(
    events: Flow<List<PendingPickupEventEntity>>,
    stops: Flow<List<RouteStopEntity>>,
    private val send: suspend () -> Int
) : ViewModel() {
    val queue: StateFlow<SyncQueue?> = combine(events, stops, ::syncQueue)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    private val sendingState = MutableStateFlow(false)

    /** True while Sync now is running, for the button's spinner. */
    val sending: StateFlow<Boolean> = sendingState.asStateFlow()

    private val resultChannel = Channel<Int>(Channel.BUFFERED)

    /** How many events were still waiting after each Sync now. */
    val results: Flow<Int> = resultChannel.receiveAsFlow()

    /** A nudge, not the only way out: events also go up on reconnect and on opening the app. */
    fun syncNow() {
        if (sendingState.value) return
        sendingState.value = true
        viewModelScope.launch {
            try {
                resultChannel.send(send())
            } finally {
                sendingState.value = false
            }
        }
    }
}
