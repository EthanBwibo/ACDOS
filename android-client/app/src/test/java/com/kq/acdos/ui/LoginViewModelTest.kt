package com.kq.acdos.ui

import com.kq.acdos.R
import com.kq.acdos.auth.AuthRepository
import com.kq.acdos.auth.FakeAuth
import com.kq.acdos.auth.SignInResult
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class LoginViewModelTest {
    /** Holds each sign-in open until the test answers it. */
    private class SlowAuth : AuthRepository by FakeAuth() {
        val answer = CompletableDeferred<SignInResult>()
        var calls = 0

        override suspend fun signIn(email: String, password: String): SignInResult {
            calls++
            return answer.await()
        }
    }

    private val auth = SlowAuth()

    @Before
    fun useTestMainDispatcher() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
    }

    @After
    fun resetMainDispatcher() {
        Dispatchers.resetMain()
    }

    @Test
    fun `signing in shows busy until the answer comes`() {
        val viewModel = LoginViewModel(auth)

        viewModel.signIn("a@b.c", "secret")
        assertEquals(LoginState.Busy, viewModel.state.value)

        auth.answer.complete(SignInResult.Success)
        assertEquals(LoginState.SignedIn, viewModel.state.value)
    }

    @Test
    fun `a second tap while signing in does nothing`() {
        val viewModel = LoginViewModel(auth)

        viewModel.signIn("a@b.c", "secret")
        viewModel.signIn("a@b.c", "secret")

        assertEquals(1, auth.calls)
    }

    @Test
    fun `wrong password and no network each get their own message`() {
        val cases = mapOf(
            SignInResult.InvalidCredentials to R.string.login_error_credentials,
            SignInResult.NetworkError to R.string.login_error_network
        )
        for ((result, message) in cases) {
            val slow = SlowAuth()
            val viewModel = LoginViewModel(slow)

            viewModel.signIn("a@b.c", "secret")
            slow.answer.complete(result)

            assertEquals(LoginState.Error(message), viewModel.state.value)
        }
    }

    @Test
    fun `an error can be retried`() {
        val viewModel = LoginViewModel(auth)
        viewModel.signIn("", "")

        viewModel.signIn("a@b.c", "secret")

        assertEquals(1, auth.calls)
    }

    @Test
    fun `an account that is not set up stays on the screen`() {
        val viewModel = LoginViewModel(auth)

        viewModel.showAccountNotSetUp()

        assertEquals(LoginState.Error(R.string.login_error_not_set_up), viewModel.state.value)
    }
}
