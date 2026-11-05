package com.kq.acdos.data

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import androidx.core.content.getSystemService
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.distinctUntilChanged

/** How the phone is connected, for the sync chip and the Sync tab. */
enum class NetworkKind {
    NONE,
    WIFI,
    MOBILE;

    val isOnline: Boolean get() = this != NONE
}

/** A network counts once it offers internet, without waiting for Android to validate it. */
fun networkKind(capabilities: NetworkCapabilities?): NetworkKind = when {
    capabilities == null -> NetworkKind.NONE
    !capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) -> NetworkKind.NONE
    capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> NetworkKind.WIFI
    else -> NetworkKind.MOBILE
}

/** Watches the phone's default network. Only listens while [network] is being collected. */
class ConnectivityMonitor(context: Context) {
    private val manager = checkNotNull(context.getSystemService<ConnectivityManager>())

    val network: Flow<NetworkKind> = callbackFlow {
        val current = manager.getNetworkCapabilities(manager.activeNetwork)
        trySend(networkKind(current))
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                trySend(networkKind(caps))
            }

            override fun onLost(network: Network) {
                trySend(NetworkKind.NONE)
            }
        }
        manager.registerDefaultNetworkCallback(callback)
        awaitClose { manager.unregisterNetworkCallback(callback) }
    }.distinctUntilChanged()
}
