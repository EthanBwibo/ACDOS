package com.kq.acdos.ui

import java.time.Instant
import java.time.LocalDate
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

    private val day = DateTimeFormatter.ofPattern("EEE d MMM", Locale.ENGLISH).withZone(ZONE)

    private val dayOfMonth = DateTimeFormatter.ofPattern("d", Locale.ROOT).withZone(ZONE)

    /** "06:50 EAT" */
    fun clock(instant: Instant): String = "${clock.format(instant)} $LABEL"

    /** "06:50", where the same row has already said EAT. */
    fun shortClock(instant: Instant): String = clock.format(instant)

    /** "Sat 31 Oct" */
    fun day(instant: Instant): String = day.format(instant)

    /** "31" */
    fun dayOfMonth(instant: Instant): String = dayOfMonth.format(instant)

    /** "06:50 EAT" today, "Sat 31 Oct, 06:50 EAT" on any other day, so old can't pass as new. */
    fun clockWithDay(instant: Instant, now: Instant = Instant.now()): String =
        if (date(instant) == date(now)) clock(instant) else "${day(instant)}, ${clock(instant)}"

    /** The date in Nairobi, which isn't always the date in UTC. */
    fun date(instant: Instant): LocalDate = instant.atZone(ZONE).toLocalDate()
}
