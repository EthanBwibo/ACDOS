package com.kq.acdos.auth

import io.github.jan.supabase.auth.status.SessionStatus
import kotlin.time.Duration.Companion.seconds
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The 401 handler's refresh (#197): after a long time offline supabase-kt shows no session
 * while it retries, so the first request after reconnecting must wait for that retry rather
 * than fail on a refresh of its own.
 */
class RefreshOrAwaitTest {
    private val wait = 15.seconds
    private var refreshes = 0
    private val refresh: suspend () -> String? = {
        refreshes++
        "refreshed"
    }

    @Test
    fun signedIn_refreshesNow() = runTest {
        val states = MutableStateFlow<TokenState>(TokenState.SignedIn("old"))

        assertEquals("refreshed", refreshOrAwait(states, wait, refresh))
        assertEquals(1, refreshes)
    }

    @Test
    fun signedOut_givesNothingWithoutTrying() = runTest {
        assertNull(refreshOrAwait(MutableStateFlow(TokenState.SignedOut), wait, refresh))
        assertEquals(0, refreshes)
    }

    @Test
    fun recovering_waitsForSupabaseKtsOwnRetryAndUsesItsToken() = runTest {
        // 7 November: the retry got through 8 s after the 401.
        val states = MutableStateFlow<TokenState>(TokenState.Recovering)

        val token = async { refreshOrAwait(states, wait, refresh) }
        advanceTimeBy(8.seconds)
        states.value = TokenState.SignedIn("from supabase-kt")

        assertEquals("from supabase-kt", token.await())
        assertEquals(0, refreshes) // never races supabase-kt with a refresh of its own
    }

    @Test
    fun recovering_givesUpAfterTheWait() = runTest {
        val states = MutableStateFlow<TokenState>(TokenState.Recovering)

        val token = async { refreshOrAwait(states, wait, refresh) }
        advanceTimeBy(16.seconds)
        states.value = TokenState.SignedIn("too late")

        assertNull(token.await())
    }

    @Test
    fun recovering_thenSignedOut_givesNothing() = runTest {
        val states = MutableStateFlow<TokenState>(TokenState.Recovering)

        val token = async { refreshOrAwait(states, wait, refresh) }
        advanceTimeBy(3.seconds)
        states.value = TokenState.SignedOut

        assertNull(token.await())
    }

    @Test
    fun supabaseKtsStates_map() {
        assertEquals(TokenState.Recovering, SessionStatus.Initializing.tokenState())
        assertEquals(TokenState.SignedOut, SessionStatus.NotAuthenticated(true).tokenState())
    }
}
