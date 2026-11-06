package com.kq.acdos.data.local

import android.content.Context
import androidx.room.AutoMigration
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters

/**
 * Local state for the Driver and Crew screens. The dispatcher is online-only and
 * has no tables here.
 *
 * Schema changes: until the M8 demo build, a version bump wipes the database
 * (destructive migration), including pickup events not yet uploaded. From the
 * M8 demo build on, the version is frozen: every change needs a Migration and a
 * migration test against the exported JSON in app/schemas.
 */
@Database(
    entities = [
        RouteEntity::class,
        RouteStopEntity::class,
        CrewPickupEntity::class,
        ScheduleChangeNoticeEntity::class,
        PresetMessageEntity::class,
        PendingPickupEventEntity::class
    ],
    version = 3,
    exportSchema = true,
    // Keep every step from here on: an update must never lose queued pickup events.
    autoMigrations = [AutoMigration(from = 2, to = 3)]
)
@TypeConverters(Converters::class)
abstract class AcdosDatabase : RoomDatabase() {
    abstract fun driverRouteDao(): DriverRouteDao

    abstract fun crewDao(): CrewDao

    abstract fun pendingPickupEventDao(): PendingPickupEventDao

    abstract fun userDataDao(): UserDataDao

    companion object {
        const val NAME = "acdos.db"

        fun build(context: Context): AcdosDatabase =
            Room.databaseBuilder(context, AcdosDatabase::class.java, NAME)
                // Only version 1, which never left development.
                .fallbackToDestructiveMigrationFrom(dropAllTables = true, 1)
                .build()
    }
}
