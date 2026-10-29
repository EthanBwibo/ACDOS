package com.kq.acdos.data.local

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Transaction
import java.time.Instant
import kotlinx.coroutines.flow.Flow

/** The crew member's next pickup, so the Pickup tab still shows with no signal. One row. */
@Entity(tableName = "crew_pickup")
data class CrewPickupEntity(
    @PrimaryKey @ColumnInfo(name = "pickup_request_id") val pickupRequestId: String,
    /** route_nodes.estimated_arrival; null until the request is on a route. */
    @ColumnInfo(name = "estimated_pickup") val estimatedPickup: Instant?,
    @ColumnInfo(name = "report_time") val reportTime: Instant,
    @ColumnInfo(name = "plate_number") val plateNumber: String?,
    @ColumnInfo(name = "fetched_at") val fetchedAt: Instant
)

/** A schedule_change_notices row for this crew member. */
@Entity(tableName = "schedule_change_notice")
data class ScheduleChangeNoticeEntity(
    @PrimaryKey val id: String,
    @ColumnInfo(name = "pickup_request_id") val pickupRequestId: String,
    /** flight_delay, standby_activation or vehicle_breakdown, as on the server. */
    val reason: String,
    @ColumnInfo(name = "previous_pickup_time") val previousPickupTime: Instant?,
    @ColumnInfo(name = "new_pickup_time") val newPickupTime: Instant?,
    @ColumnInfo(name = "issued_at") val issuedAt: Instant,
    /** Null while the notice still needs acknowledging. */
    @ColumnInfo(name = "acknowledged_at") val acknowledgedAt: Instant?
)

/** The fixed crew-to-dispatcher messages (no free text). */
@Entity(tableName = "preset_message")
data class PresetMessageEntity(@PrimaryKey val id: String, val code: String, val label: String)

@Dao
interface CrewDao {
    @Query("SELECT * FROM crew_pickup LIMIT 1")
    fun observePickup(): Flow<CrewPickupEntity?>

    /** Keeps only the latest pickup. */
    @Transaction
    suspend fun savePickup(pickup: CrewPickupEntity) {
        deletePickups()
        insertPickup(pickup)
    }

    @Query("DELETE FROM crew_pickup")
    suspend fun deletePickups()

    @Insert
    suspend fun insertPickup(pickup: CrewPickupEntity)

    @Query("SELECT * FROM schedule_change_notice ORDER BY issued_at DESC")
    fun observeNotices(): Flow<List<ScheduleChangeNoticeEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertNotices(notices: List<ScheduleChangeNoticeEntity>)

    @Query("SELECT * FROM preset_message ORDER BY label")
    fun observePresets(): Flow<List<PresetMessageEntity>>

    @Transaction
    suspend fun replacePresets(presets: List<PresetMessageEntity>) {
        deletePresets()
        insertPresets(presets)
    }

    @Query("DELETE FROM preset_message")
    suspend fun deletePresets()

    @Insert
    suspend fun insertPresets(presets: List<PresetMessageEntity>)
}
