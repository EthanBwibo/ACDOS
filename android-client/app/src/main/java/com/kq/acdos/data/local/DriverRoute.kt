package com.kq.acdos.data.local

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Transaction
import java.time.Instant
import kotlinx.coroutines.flow.Flow

/**
 * The driver's current active route: at most one row. Completed and superseded
 * routes are not kept, see [DriverRouteDao.purgeRoute].
 */
@Entity(tableName = "driver_route")
data class RouteEntity(
    @PrimaryKey val id: String,
    @ColumnInfo(name = "plate_number") val plateNumber: String,
    @ColumnInfo(name = "fetched_at") val fetchedAt: Instant
)

/**
 * One pickup on the driver's route (a route_nodes row), with the crew member's
 * name, pickup point and report time copied in so the Route tab works offline.
 * Only what the screen shows: no crew id, phone or home address text.
 */
@Entity(
    tableName = "route_stop",
    foreignKeys = [
        ForeignKey(
            entity = RouteEntity::class,
            parentColumns = ["id"],
            childColumns = ["route_id"],
            onDelete = ForeignKey.CASCADE
        )
    ],
    indices = [Index("route_id")]
)
data class RouteStopEntity(
    /** route_nodes.id, which pickup events refer to. */
    @PrimaryKey @ColumnInfo(name = "route_node_id") val routeNodeId: String,
    @ColumnInfo(name = "route_id") val routeId: String,
    @ColumnInfo(name = "seq_order") val seqOrder: Int,
    @ColumnInfo(name = "crew_name") val crewName: String,
    @ColumnInfo(name = "pickup_lat") val pickupLat: Double,
    @ColumnInfo(name = "pickup_lon") val pickupLon: Double,
    @ColumnInfo(name = "estimated_arrival") val estimatedArrival: Instant,
    /** pickup_requests.report_time: the crew member's deadline at JKIA. */
    @ColumnInfo(name = "report_time") val reportTime: Instant
)

@Dao
interface DriverRouteDao {
    @Query("SELECT * FROM driver_route LIMIT 1")
    fun observeRoute(): Flow<RouteEntity?>

    @Query("SELECT * FROM route_stop WHERE route_id = :routeId ORDER BY seq_order")
    fun observeStops(routeId: String): Flow<List<RouteStopEntity>>

    /**
     * Stores a newly assigned route. Whatever route was on the device before is
     * removed with its stops (cascade): a replaced route's crew locations do
     * not stay on the driver's phone.
     */
    @Transaction
    suspend fun saveActiveRoute(route: RouteEntity, stops: List<RouteStopEntity>) {
        deleteAllRoutes()
        insertRoute(route)
        insertStops(stops)
    }

    /** Removes a route and its stops, when the server reports it completed or superseded. */
    @Query("DELETE FROM driver_route WHERE id = :routeId")
    suspend fun purgeRoute(routeId: String)

    @Query("DELETE FROM driver_route")
    suspend fun deleteAllRoutes()

    @Insert
    suspend fun insertRoute(route: RouteEntity)

    @Insert
    suspend fun insertStops(stops: List<RouteStopEntity>)
}
