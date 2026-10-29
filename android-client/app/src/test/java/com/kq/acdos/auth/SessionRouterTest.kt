package com.kq.acdos.auth

import com.kq.acdos.ui.CrewHomeActivity
import com.kq.acdos.ui.DispatcherHomeActivity
import com.kq.acdos.ui.DriverHomeActivity
import com.kq.acdos.ui.homeActivityFor
import java.io.IOException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Role routing after sign-in and on a cold start, with a fake Supabase. */
class SessionRouterTest {
    private val userData = FakeUserData()

    private fun router(auth: FakeAuth, cache: FakeCache = FakeCache()) =
        SessionRouter(auth, cache, userData)

    private fun found(role: AppRole) = ProfileResult.Found(Profile(USER, role, "Test User"))

    @Test
    fun driver_opensDriverHome() = runTest {
        val auth = FakeAuth(profileResult = found(AppRole.DRIVER))
        val cache = FakeCache()

        val destination = router(auth, cache).resolveProfile()

        assertEquals(Destination.Home(Profile(USER, AppRole.DRIVER, "Test User")), destination)
        assertEquals(DriverHomeActivity::class.java, homeActivityFor(AppRole.DRIVER))
        assertEquals(AppRole.DRIVER, cache.stored?.role)
    }

    @Test
    fun crew_opensCrewHome() = runTest {
        val auth = FakeAuth(profileResult = found(AppRole.CREW))

        val destination = router(auth).resolveProfile()

        assertEquals(AppRole.CREW, (destination as Destination.Home).profile.role)
        assertEquals(CrewHomeActivity::class.java, homeActivityFor(AppRole.CREW))
    }

    @Test
    fun dispatcher_opensDispatcherHome() = runTest {
        val auth = FakeAuth(profileResult = found(AppRole.DISPATCHER))

        val destination = router(auth).resolveProfile()

        assertEquals(AppRole.DISPATCHER, (destination as Destination.Home).profile.role)
        assertEquals(DispatcherHomeActivity::class.java, homeActivityFor(AppRole.DISPATCHER))
    }

    @Test
    fun noProfilesRow_signsOutAndSaysNotSetUp() = runTest {
        val auth = FakeAuth(profileResult = ProfileResult.Missing)
        val cache = FakeCache(Profile(USER, AppRole.DRIVER, "Stale"))

        val destination = router(auth, cache).resolveProfile()

        assertEquals(Destination.AccountNotSetUp, destination)
        assertEquals(1, auth.signOutCalls)
        assertNull(cache.stored)
    }

    @Test
    fun networkError_keepsSessionAndOffersRetry() = runTest {
        val auth = FakeAuth(profileResult = ProfileResult.NetworkError(IOException("offline")))

        val destination = router(auth).resolveProfile()

        assertEquals(Destination.Retry, destination)
        assertEquals(0, auth.signOutCalls)
        assertEquals(USER, auth.storedUserId)
    }

    @Test
    fun coldStartOffline_routesOnCachedRoleWithoutNetwork() = runTest {
        val auth = FakeAuth(profileResult = ProfileResult.NetworkError(IOException("offline")))
        val cache = FakeCache(Profile(USER, AppRole.CREW, "Test User"))

        val destination = router(auth, cache).onColdStart()

        assertEquals(Destination.Home(Profile(USER, AppRole.CREW, "Test User")), destination)
        assertEquals(0, auth.fetchCalls)
    }

    @Test
    fun coldStartWithoutCache_readsProfile() = runTest {
        val auth = FakeAuth(profileResult = found(AppRole.DRIVER))

        val destination = router(auth).onColdStart()

        assertTrue(destination is Destination.Home)
        assertEquals(1, auth.fetchCalls)
    }

    @Test
    fun coldStart_ignoresCacheOfAnotherUser() = runTest {
        val auth = FakeAuth(profileResult = ProfileResult.NetworkError(IOException("offline")))
        val cache = FakeCache(Profile("someone-else", AppRole.DISPATCHER, "Other"))

        val destination = router(auth, cache).onColdStart()

        assertEquals(Destination.Retry, destination)
    }

    @Test
    fun coldStartWithoutSession_opensLogin() = runTest {
        val auth = FakeAuth(storedUserId = null)

        assertEquals(Destination.Login, router(auth).onColdStart())
        assertEquals(0, auth.fetchCalls)
    }

    @Test
    fun sessionGone_opensLoginAndClearsCache() = runTest {
        val cache = FakeCache(Profile(USER, AppRole.DRIVER, "Test User"))

        val auth = FakeAuth(profileResult = ProfileResult.NoSession)

        val destination = router(auth, cache).resolveProfile()

        assertEquals(Destination.Login, destination)
        assertNull(cache.stored)
    }

    @Test
    fun sessionEndedByServer_clearsCachedNameAndRole() = runTest {
        val cache = FakeCache(Profile(USER, AppRole.CREW, "Test User"))

        router(FakeAuth(), cache).onSessionEnded()

        assertNull(cache.stored)
    }

    @Test
    fun signOut_clearsUserData() = runTest {
        val auth = FakeAuth()
        val cache = FakeCache(Profile(USER, AppRole.DRIVER, "Test User"))

        router(auth, cache).signOut()

        assertEquals(1, auth.signOutCalls)
        assertNull(cache.stored)
        assertEquals(1, userData.clearCalls)
    }

    @Test
    fun sessionEndedByServer_clearsUserData() = runTest {
        router(FakeAuth()).onSessionEnded()

        assertEquals(1, userData.clearCalls)
    }

    @Test
    fun noProfilesRow_clearsUserData() = runTest {
        router(FakeAuth(profileResult = ProfileResult.Missing)).resolveProfile()

        assertEquals(1, userData.clearCalls)
    }

    @Test
    fun sessionGone_clearsUserData() = runTest {
        router(FakeAuth(profileResult = ProfileResult.NoSession)).resolveProfile()

        assertEquals(1, userData.clearCalls)
    }

    @Test
    fun networkError_keepsUserData() = runTest {
        val auth = FakeAuth(profileResult = ProfileResult.NetworkError(IOException("offline")))

        router(auth).resolveProfile()

        assertEquals(0, userData.clearCalls)
    }

    @Test
    fun appRole_readsOnlyKnownValues() {
        assertEquals(AppRole.DRIVER, AppRole.fromDb("driver"))
        assertEquals(AppRole.CREW, AppRole.fromDb("crew"))
        assertEquals(AppRole.DISPATCHER, AppRole.fromDb("dispatcher"))
        assertNull(AppRole.fromDb("pilot"))
        assertFalse(AppRole.entries.any { AppRole.fromDb(it.dbValue.uppercase()) != null })
    }
}
