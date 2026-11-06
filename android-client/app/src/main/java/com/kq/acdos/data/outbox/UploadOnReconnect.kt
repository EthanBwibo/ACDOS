package com.kq.acdos.data.outbox

import com.kq.acdos.data.NetworkKind
import kotlin.time.Duration
import kotlin.time.Duration.Companion.seconds
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map

/** The gaps between tries after a reconnect: about two minutes, then the next reconnect. */
val RECONNECT_RETRY_WAITS: List<Duration> = listOf(5.seconds, 15.seconds, 30.seconds, 60.seconds)

/**
 * What makes "Sends when signal returns" true. A phone can join a network
 * before it can reach the server, so one try isn't enough: [send] runs again
 * after each of [waits] until it reports nothing waiting. Losing the signal
 * stops the tries, and moving between Wi-Fi and mobile data doesn't start them.
 *
 * @param send uploads the outbox and returns how many events are still waiting.
 */
suspend fun uploadOnReconnect(
    network: Flow<NetworkKind>,
    send: suspend () -> Int,
    waits: List<Duration> = RECONNECT_RETRY_WAITS
) {
    network.map { it.isOnline }.distinctUntilChanged().collectLatest { online ->
        if (online) sendUntilNothingWaits(send, waits)
    }
}

private suspend fun sendUntilNothingWaits(send: suspend () -> Int, waits: List<Duration>) {
    for (wait in waits) {
        if (send() == 0) return
        delay(wait)
    }
    send()
}
