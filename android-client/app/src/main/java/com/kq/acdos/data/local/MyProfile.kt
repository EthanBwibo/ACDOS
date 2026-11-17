package com.kq.acdos.data.local

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import java.time.Instant
import kotlinx.coroutines.flow.Flow

/**
 * What the Profile screen (#231) shows beyond the name, so it opens with no
 * signal. One row, for whoever is signed in: crew fill the crew fields from
 * GET /crew/me, drivers the vehicle fields from GET /drivers/me. A row with
 * no vehicle means the server said no van is assigned; no row means it has
 * never been loaded.
 */
@Entity(tableName = "my_profile")
data class MyProfileEntity(
    @PrimaryKey val id: Int = ONLY_ROW,
    /** crew_members.role as the roster has it, e.g. cabin_crew. */
    @ColumnInfo(name = "crew_role") val crewRole: String? = null,
    /** The pickup zone nearest the home location, e.g. "Westlands, Nairobi". */
    @ColumnInfo(name = "home_zone") val homeZone: String? = null,
    @ColumnInfo(name = "vehicle_plate") val vehiclePlate: String? = null,
    @ColumnInfo(name = "vehicle_seats") val vehicleSeats: Int? = null,
    /** The server's value, e.g. broken_down. */
    @ColumnInfo(name = "vehicle_status") val vehicleStatus: String? = null,
    @ColumnInfo(name = "fetched_at") val fetchedAt: Instant
) {
    companion object {
        const val ONLY_ROW = 0
    }
}

@Dao
interface MyProfileDao {
    @Query("SELECT * FROM my_profile WHERE id = ${MyProfileEntity.ONLY_ROW}")
    fun observe(): Flow<MyProfileEntity?>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun save(profile: MyProfileEntity)
}
