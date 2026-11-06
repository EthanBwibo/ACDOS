package com.kq.acdos.ui

import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.annotation.StringRes
import androidx.core.view.isVisible
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.kq.acdos.AppContainer
import com.kq.acdos.R
import com.kq.acdos.data.NetworkKind
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * Keeps view_status_banners up to date: [offlineText] with no signal, otherwise
 * [failure], the latest failed load or null. Offline explains a failed load by
 * itself, so the two never show together.
 */
fun ComponentActivity.showStatusBanners(
    container: AppContainer,
    @StringRes offlineText: Int,
    failure: Flow<String?>
) {
    val offline = findViewById<TextView>(R.id.offline_banner)
    val error = findViewById<TextView>(R.id.load_error)
    offline.setText(offlineText)
    lifecycleScope.launch {
        repeatOnLifecycle(Lifecycle.State.STARTED) {
            combine(container.connectivity.network, failure, ::bannerState).collect { state ->
                offline.isVisible = state.offline
                error.isVisible = state.failure != null
                error.text = state.failure
            }
        }
    }
}

data class BannerState(val offline: Boolean, val failure: String?)

fun bannerState(network: NetworkKind, failure: String?) =
    BannerState(offline = !network.isOnline, failure = failure.takeIf { network.isOnline })
