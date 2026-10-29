package com.kq.acdos.auth

import com.kq.acdos.data.local.UserDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

// Stand-ins for Supabase, the profile cache and Room, shared by the auth tests.

/** The signed-in user in these tests. */
const val USER = "00000000-0000-0000-0000-00000000000a"

class FakeAuth(
    var storedUserId: String? = USER,
    var profileResult: ProfileResult = ProfileResult.Missing
) : AuthRepository {
    var signOutCalls = 0
    var fetchCalls = 0

    override suspend fun storedSessionUserId() = storedUserId

    override suspend fun signIn(email: String, password: String) = SignInResult.Success

    override suspend fun fetchProfile(): ProfileResult {
        fetchCalls++
        return profileResult
    }

    override suspend fun signOut() {
        signOutCalls++
        storedUserId = null
    }

    override val sessionEnded: Flow<Unit> = emptyFlow()

    override suspend fun accessToken(): String? = null

    override suspend fun refreshAccessToken(): String? = null
}

class FakeCache(var stored: Profile? = null) : ProfileCache {
    override suspend fun get(userId: String) = stored?.takeIf { it.userId == userId }

    override suspend fun put(profile: Profile) {
        stored = profile
    }

    override suspend fun clear() {
        stored = null
    }
}

class FakeUserData : UserDataStore {
    var clearCalls = 0

    override suspend fun clearUserData() {
        clearCalls++
    }
}
