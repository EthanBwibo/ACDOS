package com.kq.acdos.ui

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Every time the app shows, in one place. The operation runs on Nairobi time,
 * so times are always shown in Africa/Nairobi and labelled EAT, whatever zone
 * the phone is set to: crew back from an international trip may still have
 * their phone on another zone. Kenya has no daylight saving, so EAT is always
 * UTC+3. Used by the Driver screens and, later, #29 and the Crew screens.
 */
object Times {
    val ZONE: ZoneId = ZoneId.of("Africa/Nairobi")

    private const val LABEL = "EAT"

    private val clock = DateTimeFormatter.ofPattern("HH:mm", Locale.ROOT).withZone(ZONE)

    /** "06:50 EAT" */
    fun clock(instant: Instant): String = "${clock.format(instant)} $LABEL"
}
