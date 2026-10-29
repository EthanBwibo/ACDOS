package com.kq.acdos.data.local

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Transaction

/**
 * The signed-in user's local data, as SessionRouter sees it: an interface so
 * its tests can use a fake instead of Room.
 */
fun interface UserDataStore {
    suspend fun clearUserData()
}

/** What leaves the device when the user signs out. */
@Dao
interface UserDataDao : UserDataStore {
    /**
     * Deletes the cached route and stops (crew names and pickup points), the
     * crew pickup, notices and presets, and outbox events already uploaded.
     * Events not yet uploaded stay, including conflicts: they are kept until
     * their own driver signs in again (see PendingPickupEventDao.pending).
     */
    @Transaction
    override suspend fun clearUserData() {
        deleteRoutes()
        deleteCrewPickups()
        deleteNotices()
        deletePresets()
        deleteSyncedEvents()
    }

    // route_stop goes with its route (ON DELETE CASCADE).
    @Query("DELETE FROM driver_route")
    suspend fun deleteRoutes()

    @Query("DELETE FROM crew_pickup")
    suspend fun deleteCrewPickups()

    @Query("DELETE FROM schedule_change_notice")
    suspend fun deleteNotices()

    @Query("DELETE FROM preset_message")
    suspend fun deletePresets()

    @Query("DELETE FROM pickup_event_outbox WHERE synced_at IS NOT NULL")
    suspend fun deleteSyncedEvents()
}
