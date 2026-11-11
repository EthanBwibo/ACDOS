package com.kq.acdos.ui

import android.content.Intent
import android.os.Bundle
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.annotation.StringRes
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.isVisible
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.google.android.material.button.MaterialButton
import com.google.android.material.dialog.MaterialAlertDialogBuilder
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

    /** The account signed in but has no profiles row. Held here so it survives a recreate. */
    fun showAccountNotSetUp() {
        _state.value = LoginState.Error(R.string.login_error_not_set_up)
    }

    /** Signed out because the account's role changed since it was cached (#116). */
    fun showRoleChanged() {
        _state.value = LoginState.Error(R.string.login_error_role_changed)
    }

    fun signIn(email: String, password: String) {
        val inProgress = _state.value == LoginState.Busy || _state.value == LoginState.SignedIn
        if (inProgress) return
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
 * The theme is on this screen too, so it can be set before signing in.
 */
class LoginActivity : AppCompatActivity() {
    private val container by lazy { (application as AcdosApplication).container }
    private val viewModel: LoginViewModel by viewModels {
        viewModelFactory {
            initializer {
                LoginViewModel(container.authRepository)
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
        val signIn = findViewById<MaterialButton>(R.id.sign_in)
        val error = findViewById<TextView>(R.id.error)

        if (intent.getBooleanExtra(EXTRA_ACCOUNT_NOT_SET_UP, false) && savedInstanceState == null) {
            viewModel.showAccountNotSetUp()
        }
        if (intent.getBooleanExtra(EXTRA_ROLE_CHANGED, false) && savedInstanceState == null) {
            viewModel.showRoleChanged()
        }

        val submit = {
            hideKeyboard()
            viewModel.signIn(email.text.toString(), password.text.toString())
        }
        signIn.setOnClickListener { submit() }
        password.setOnEditorActionListener { _, action, _ ->
            if (action == EditorInfo.IME_ACTION_DONE) submit()
            action == EditorInfo.IME_ACTION_DONE
        }
        findViewById<Button>(R.id.forgot_password).setOnClickListener { explainPasswordReset() }
        findViewById<Button>(R.id.theme).apply {
            val store = container.themeStore
            text = getString(R.string.login_theme, getString(store.mode().label))
            setOnClickListener { showThemeDialog(store) }
        }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.state.collect { state ->
                    val busy = state == LoginState.Busy || state == LoginState.SignedIn
                    signIn.showLoading(
                        busy,
                        if (busy) R.string.login_signing_in else R.string.login_sign_in
                    )
                    email.isEnabled = !busy
                    password.isEnabled = !busy
                    error.isVisible = state is LoginState.Error
                    if (state is LoginState.Error) {
                        val text = getString(state.message)
                        error.text = if (state.detail == null) text else "$text\n${state.detail}"
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

    /** There is no reset flow: accounts are created for users, not by them. */
    private fun explainPasswordReset() {
        MaterialAlertDialogBuilder(this)
            .setMessage(R.string.login_forgot_message)
            .setPositiveButton(R.string.action_ok, null)
            .show()
    }

    private fun hideKeyboard() {
        WindowCompat.getInsetsController(window, window.decorView)
            .hide(WindowInsetsCompat.Type.ime())
    }

    companion object {
        const val EXTRA_ACCOUNT_NOT_SET_UP = "account_not_set_up"
        const val EXTRA_ROLE_CHANGED = "role_changed"
    }
}
