package com.kq.acdos.ui

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.annotation.StringRes
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.kq.acdos.AcdosApplication
import com.kq.acdos.MainActivity
import com.kq.acdos.R
import com.kq.acdos.auth.AuthRepository
import com.kq.acdos.auth.SignInResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface LoginState {
    data object Idle : LoginState

    data object Busy : LoginState

    data class Error(@StringRes val message: Int, val detail: String? = null) : LoginState

    data object SignedIn : LoginState
}

class LoginViewModel(private val auth: AuthRepository) : ViewModel() {
    private val _state = MutableStateFlow<LoginState>(LoginState.Idle)
    val state: StateFlow<LoginState> = _state.asStateFlow()

    fun signIn(email: String, password: String) {
        if (email.isBlank() || password.isEmpty()) {
            _state.value = LoginState.Error(R.string.login_error_empty)
            return
        }
        _state.value = LoginState.Busy
        viewModelScope.launch {
            _state.value = when (val result = auth.signIn(email.trim(), password)) {
                SignInResult.Success -> LoginState.SignedIn
                SignInResult.InvalidCredentials ->
                    LoginState.Error(R.string.login_error_credentials)
                SignInResult.NetworkError -> LoginState.Error(R.string.login_error_network)
                is SignInResult.Rejected ->
                    LoginState.Error(R.string.login_error_rejected, result.message)
            }
        }
    }
}

/**
 * Email and password only: accounts are created by the dispatcher, and the
 * role comes from profiles.role, so there is no sign-up and no role choice.
 */
class LoginActivity : AppCompatActivity() {
    private val viewModel: LoginViewModel by viewModels {
        viewModelFactory {
            initializer {
                LoginViewModel((application as AcdosApplication).container.authRepository)
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_login)
        applySystemBarPadding(findViewById(R.id.main))

        val email = findViewById<EditText>(R.id.email)
        val password = findViewById<EditText>(R.id.password)
        val signIn = findViewById<Button>(R.id.sign_in)
        val progress = findViewById<ProgressBar>(R.id.progress)
        val error = findViewById<TextView>(R.id.error)

        if (intent.getBooleanExtra(EXTRA_ACCOUNT_NOT_SET_UP, false) && savedInstanceState == null) {
            error.setText(R.string.login_error_not_set_up)
            error.visibility = View.VISIBLE
        }

        signIn.setOnClickListener {
            viewModel.signIn(email.text.toString(), password.text.toString())
        }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    val busy = state == LoginState.Busy || state == LoginState.SignedIn
                    progress.visibility = if (busy) View.VISIBLE else View.GONE
                    signIn.isEnabled = !busy
                    if (state is LoginState.Error) {
                        val text = getString(state.message)
                        error.text = if (state.detail == null) text else "$text\n${state.detail}"
                        error.visibility = View.VISIBLE
                    } else if (state != LoginState.Idle) {
                        error.visibility = View.GONE
                    }
                    if (state == LoginState.SignedIn) {
                        // MainActivity reads profiles.role and opens the right screen.
                        startActivity(
                            Intent(this@LoginActivity, MainActivity::class.java)
                                .addFlags(NEW_CLEAR_TASK)
                        )
                    }
                }
            }
        }
    }

    companion object {
        const val EXTRA_ACCOUNT_NOT_SET_UP = "account_not_set_up"
    }
}
