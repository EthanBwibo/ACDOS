package com.kq.acdos.auth

import java.io.IOException
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test

/** How a failed sign-in call is reported to the Login screen. */
class SignInResultTest {

    @Test
    fun success() = runTest {
        assertEquals(SignInResult.Success, runSignIn { })
    }

    @Test
    fun unexpectedException_isANetworkError() = runTest {
        val logged = mutableListOf<Throwable>()
        val failure = IllegalStateException("malformed token response")

        val result = runSignIn(onNetworkError = { logged += it }) { throw failure }

        assertEquals(SignInResult.NetworkError, result)
        assertEquals(listOf<Throwable>(failure), logged)
    }

    @Test
    fun timeout_isANetworkError() = runTest {
        // Ktor's request timeout is an IOException, not supabase-kt's HttpRequestException.
        assertEquals(SignInResult.NetworkError, runSignIn { throw IOException("timed out") })
    }

    @Test
    fun cancellation_isRethrown() = runTest {
        try {
            runSignIn { throw CancellationException("screen closed") }
            fail("cancellation was swallowed")
        } catch (expected: CancellationException) {
            assertEquals("screen closed", expected.message)
        }
    }
}
