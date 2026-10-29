package com.kq.acdos

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.ProgressBar
import android.widget.TextView
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.kq.acdos.auth.Destination
import com.kq.acdos.auth.SessionRouter
import com.kq.acdos.ui.applySystemBarPadding
import com.kq.acdos.ui.openHome
import com.kq.acdos.ui.openLogin
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** [destination] is null while it is being worked out. */
class StartupViewModel(private val router: SessionRouter) : ViewModel() {
    private val _destination = MutableStateFlow<Destination?>(null)
    val destination: StateFlow<Destination?> = _destination.asStateFlow()

    init {
        viewModelScope.launch { _destination.value = router.onColdStart() }
    }

    fun retry() {
        _destination.value = null
        viewModelScope.launch { _destination.value = router.resolveProfile() }
    }

    fun signOut() {
        _destination.value = null
        viewModelScope.launch {
            router.signOut()
            _destination.value = Destination.Login
        }
    }
}

/**
 * Launcher. Sends the user to sign-in or to their role's home screen. Sign-in
 * also returns here, so the role is decided in one place.
 */
class MainActivity : AppCompatActivity() {
    private val container by lazy { (application as AcdosApplication).container }

    private val viewModel: StartupViewModel by viewModels {
        viewModelFactory { initializer { StartupViewModel(container.sessionRouter) } }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_main)
        applySystemBarPadding(findViewById(R.id.main))

        val progress = findViewById<ProgressBar>(R.id.progress)
        val message = findViewById<TextView>(R.id.message)
        val retry = findViewById<Button>(R.id.retry)
        val signOut = findViewById<Button>(R.id.sign_out)

        if (!container.isConfigured) {
            progress.visibility = View.GONE
            message.setText(R.string.startup_not_configured)
            message.visibility = View.VISIBLE
            return
        }

        retry.setOnClickListener { viewModel.retry() }
        signOut.setOnClickListener { viewModel.signOut() }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.destination.collect { destination ->
                    val isRetry = destination == Destination.Retry
                    progress.visibility = if (destination == null) View.VISIBLE else View.GONE
                    message.visibility = if (isRetry) View.VISIBLE else View.GONE
                    retry.visibility = if (isRetry) View.VISIBLE else View.GONE
                    signOut.visibility = if (isRetry) View.VISIBLE else View.GONE
                    if (isRetry) message.setText(R.string.startup_profile_unavailable)

                    when (destination) {
                        is Destination.Home -> openHome(destination.profile)
                        Destination.Login -> openLogin()
                        Destination.AccountNotSetUp -> openLogin(accountNotSetUp = true)
                        Destination.Retry, null -> Unit
                    }
                }
            }
        }
    }
}
