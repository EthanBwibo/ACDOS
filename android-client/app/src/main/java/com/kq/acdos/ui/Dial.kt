package com.kq.acdos.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import com.kq.acdos.R

/**
 * Opens the phone's dialer with [phone] filled in (#255). ACTION_DIAL needs no
 * permission and places no call: the person taps call themselves. Crew and
 * drivers only call around a pickup; every message still goes through the
 * dispatcher.
 */
fun dialIntent(phone: String): Intent = Intent(Intent.ACTION_DIAL, Uri.parse("tel:$phone"))

fun Context.dial(phone: String) {
    try {
        startActivity(dialIntent(phone))
    } catch (e: ActivityNotFoundException) {
        // A tablet with no dialer.
        Toast.makeText(this, R.string.call_no_dialer, Toast.LENGTH_LONG).show()
    }
}
