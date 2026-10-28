package com.kq.acdos.auth

import com.kq.acdos.ui.CrewHomeActivity
import com.kq.acdos.ui.DispatcherHomeActivity
import com.kq.acdos.ui.DriverHomeActivity
import com.kq.acdos.ui.homeActivityFor
import java.io.IOException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Role routing after sign-in and on a cold start, with a fake Supabase. */
class SessionRouterTest {

    private class FakeAuth(
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

    private class FakeCache(var stored: Profile? = null) : ProfileCache {
        override suspend fun get(userId: String) = stored?.takeIf { it.userId == userId }

        override suspend fun put(profile: Profile) {
            stored = profile
        }

        override suspend fun clear() {
            stored = null
        }
    }

    private fun found(role: AppRole) = ProfileResult.Found(Profile(USER, role, "Test User"))

    @Test
    fun driver_opensDriverHome() = runTest {
        val auth = FakeAuth(profileResult = found(AppRole.DRIVER))
        val cache = FakeCache()

        val destination = SessionRouter(auth, cache).resolveProfile()

        assertEquals(Destination.Home(Profile(USER, AppRole.DRIVER, "Test User")), destination)
        assertEquals(DriverHomeActivity::class.java, homeActivityFor(AppRole.DRIVER))
        assertEquals(AppRole.DRIVER, cache.stored?.role)
    }

    @Test
    fun crew_opensCrewHome() = runTest {
        val auth = FakeAuth(profileResult = found(AppRole.CREW))

        val destination = SessionRouter(auth, FakeCache()).resolveProfile()

        assertEquals(AppRole.CREW, (destination as Destination.Home).profile.role)
        assertEquals(CrewHomeActivity::class.java, homeActivityFor(AppRole.CREW))
    }

    @Test
    fun dispatcher_opensDispatcherHome() = runTest {
        val auth = FakeAuth(profileResult = found(AppRole.DISPATCHER))

        val destination = SessionRouter(auth, FakeCache()).resolveProfile()

        assertEquals(AppRole.DISPATCHER, (destination as Destination.Home).profile.role)
        assertEquals(DispatcherHomeActivity::class.java, homeActivityFor(AppRole.DISPATCHER))
    }

    @Test
    fun noProfilesRow_signsOutAndSaysNotSetUp() = runTest {
        val auth = FakeAuth(profileResult = ProfileResult.Missing)
        val cache = FakeCache(Profile(USER, AppRole.DRIVER, "Stale"))

        val destination = SessionRouter(auth, cache).resolveProfile()

        assertEquals(Destination.AccountNotSetUp, destination)
        assertEquals(1, auth.signOutCalls)
        assertNull(cache.stored)
    }

    @Test
    fun networkError_keepsSessionAndOffersRetry() = runTest {
        val auth = FakeAuth(profileResult = ProfileResult.NetworkError(IOException("offline")))

        val destination = SessionRouter(auth, FakeCache()).resolveProfile()

        assertEquals(Destination.Retry, destination)
        assertEquals(0, auth.signOutCalls)
        assertEquals(USER, auth.storedUserId)
    }

    @Test
    fun coldStartOffline_routesOnCachedRoleWithoutNetwork() = runTest {
        val auth = FakeAuth(profileResult = ProfileResult.NetworkError(IOException("offline")))
        val cache = FakeCache(Profile(USER, AppRole.CREW, "Test User"))

        val destination = SessionRouter(auth, cache).onColdStart()

        assertEquals(Destination.Home(Profile(USER, AppRole.CREW, "Test User")), destination)
        assertEquals(0, auth.fetchCalls)
    }

    @Test
    fun coldStartWithoutCache_readsProfile() = runTest {
        val auth = FakeAuth(profileResult = found(AppRole.DRIVER))

        val destination = SessionRouter(auth, FakeCache()).onColdStart()

        assertTrue(destination is Destination.Home)
        assertEquals(1, auth.fetchCalls)
    }

    @Test
    fun coldStart_ignoresCacheOfAnotherUser() = runTest {
        val auth = FakeAuth(profileResult = ProfileResult.NetworkError(IOException("offline")))
        val cache = FakeCache(Profile("someone-else", AppRole.DISPATCHER, "Other"))

        val destination = SessionRouter(auth, cache).onColdStart()

        assertEquals(Destination.Retry, destination)
    }

    @Test
    fun coldStartWithoutSession_opensLogin() = runTest {
        val auth = FakeAuth(storedUserId = null)

        assertEquals(Destination.Login, SessionRouter(auth, FakeCache()).onColdStart())
        assertEquals(0, auth.fetchCalls)
    }

    @Test
    fun sessionGone_opensLoginAndClearsCache() = runTest {
        val cache = FakeCache(Profile(USER, AppRole.DRIVER, "Test User"))

        val auth = FakeAuth(profileResult = ProfileResult.NoSession)

        val destination = SessionRouter(auth, cache).resolveProfile()

        assertEquals(Destination.Login, destination)
        assertNull(cache.stored)
    }

    @Test
    fun appRole_readsOnlyKnownValues() {
        assertEquals(AppRole.DRIVER, AppRole.fromDb("driver"))
        assertEquals(AppRole.CREW, AppRole.fromDb("crew"))
        assertEquals(AppRole.DISPATCHER, AppRole.fromDb("dispatcher"))
        assertNull(AppRole.fromDb("pilot"))
        assertFalse(AppRole.entries.any { AppRole.fromDb(it.dbValue.uppercase()) != null })
    }

    private companion object {
        const val USER = "00000000-0000-0000-0000-00000000000a"
    }
}
