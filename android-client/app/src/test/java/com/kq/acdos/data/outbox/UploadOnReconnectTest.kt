package com.kq.acdos.data.outbox

import com.kq.acdos.data.NetworkKind
import kotlin.time.Duration.Companion.minutes
import kotlin.time.Duration.Companion.seconds
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class UploadOnReconnectTest {
    private val network = MutableStateFlow(NetworkKind.NONE)
    private var sends = 0

    /** What each send reports as still waiting; the last value repeats. */
    private fun TestScope.watch(vararg waiting: Int) {
        backgroundScope.launch {
            uploadOnReconnect(network, send = { waiting[minOf(sends++, waiting.lastIndex)] })
        }
        runCurrent()
    }

    private fun TestScope.after(seconds: Int) {
        advanceTimeBy(seconds.seconds)
        runCurrent()
    }

    @Test
    fun `offline sends nothing, and the reconnect sends without a tap`() = runTest {
        watch(0)
        assertEquals(0, sends)

        network.value = NetworkKind.WIFI
        runCurrent()

        assertEquals(1, sends)
    }

    @Test
    fun `nothing waiting means no more tries`() = runTest {
        watch(0)
        network.value = NetworkKind.MOBILE
        runCurrent()

        advanceTimeBy(10.minutes)
        runCurrent()

        assertEquals(1, sends)
    }

    @Test
    fun `a failed try is retried until the queue is empty`() = runTest {
        watch(2, 2, 0)
        network.value = NetworkKind.WIFI
        runCurrent()
        assertEquals(1, sends)

        after(5)
        assertEquals(2, sends)
        after(14)
        assertEquals(2, sends)
        after(1)
        assertEquals(3, sends)

        advanceTimeBy(10.minutes)
        runCurrent()
        assertEquals(3, sends)
    }

    @Test
    fun `the tries end after the last wait`() = runTest {
        watch(1)
        network.value = NetworkKind.WIFI
        runCurrent()

        advanceTimeBy(10.minutes)
        runCurrent()

        assertEquals(RECONNECT_RETRY_WAITS.size + 1, sends)
    }

    @Test
    fun `losing the signal stops the tries, and the next reconnect starts again`() = runTest {
        watch(1)
        network.value = NetworkKind.WIFI
        runCurrent()
        network.value = NetworkKind.NONE
        after(5)
        assertEquals(1, sends)

        network.value = NetworkKind.MOBILE
        runCurrent()

        assertEquals(2, sends)
    }

    @Test
    fun `moving from Wi-Fi to mobile data is not a reconnect`() = runTest {
        watch(0)
        network.value = NetworkKind.WIFI
        runCurrent()

        network.value = NetworkKind.MOBILE
        runCurrent()

        assertEquals(1, sends)
    }
}
