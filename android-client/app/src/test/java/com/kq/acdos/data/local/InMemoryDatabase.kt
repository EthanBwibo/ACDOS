package com.kq.acdos.data.local

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider

/** A fresh in-memory database per test, with the same schema and converters as the app's. */
fun inMemoryDatabase(): AcdosDatabase = Room.inMemoryDatabaseBuilder(
    ApplicationProvider.getApplicationContext(),
    AcdosDatabase::class.java
).allowMainThreadQueries().build()
