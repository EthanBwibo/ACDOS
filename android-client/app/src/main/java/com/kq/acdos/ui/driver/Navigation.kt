package com.kq.acdos.ui.driver

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.view.View
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.R
import java.util.Locale

const val GOOGLE_MAPS_PACKAGE = "com.google.android.apps.maps"

/**
 * What "Navigate" tries, in order (#228):
 * 1. Google Maps straight into turn-by-turn. The package is set, so no chooser appears.
 * 2. Any maps app, with the stop pinned. Android shows its chooser if there are several.
 *
 * Only the coordinates leave the app: no crew name goes to another app.
 */
fun navigationIntents(lat: Double, lon: Double): List<Intent> {
    // Locale.ROOT: a decimal point whatever the phone's language.
    val point = String.format(Locale.ROOT, "%.5f,%.5f", lat, lon)
    return listOf(
        Intent(Intent.ACTION_VIEW, Uri.parse("google.navigation:q=$point"))
            .setPackage(GOOGLE_MAPS_PACKAGE),
        Intent(Intent.ACTION_VIEW, Uri.parse("geo:$point?q=$point"))
    )
}

/**
 * Starts the first intent some app can handle. Trying is enough, so the app needs no
 * `<queries>` entry to see which maps apps are installed. False if none could start.
 */
fun startFirst(intents: List<Intent>, start: (Intent) -> Unit): Boolean = intents.any {
    try {
        start(it)
        true
    } catch (e: ActivityNotFoundException) {
        false
    }
}

/**
 * Hands the stop to a maps app for turn-by-turn. If there is none, a snackbar on [view],
 * above [anchor] when given (the bottom nav).
 */
fun navigateTo(view: View, lat: Double, lon: Double, anchor: View? = null) {
    if (!startFirst(navigationIntents(lat, lon), view.context::startActivity)) {
        Snackbar.make(view, R.string.route_no_maps_app, Snackbar.LENGTH_LONG)
            .setAnchorView(anchor)
            .show()
    }
}
