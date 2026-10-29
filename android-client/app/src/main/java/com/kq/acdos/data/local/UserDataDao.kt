package com.kq.acdos.data.local

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Transaction

/** What leaves the device when the user signs out. */
@Dao
interface UserDataDao {
    /**
     * Deletes the cached route and stops (crew names and pickup points), the
     * crew pickup, notices and presets, and outbox events already uploaded.
     * Events not yet uploaded stay, including conflicts: they are kept until
     * their own driver signs in again (see PendingPickupEventDao.pending).
     */
    @Transaction
    suspend fun clearUserData() {
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
