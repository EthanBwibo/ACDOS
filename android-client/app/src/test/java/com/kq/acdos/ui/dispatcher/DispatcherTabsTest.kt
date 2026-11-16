package com.kq.acdos.ui.dispatcher

import android.os.Looper
import androidx.fragment.app.Fragment
import androidx.test.core.app.ApplicationProvider
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.kq.acdos.AcdosApplication
import com.kq.acdos.AppContainer
import com.kq.acdos.R
import com.kq.acdos.auth.AuthRepository
import com.kq.acdos.auth.ProfileResult
import com.kq.acdos.auth.SignInResult
import com.kq.acdos.data.DispatchRepository
import com.kq.acdos.data.MessagesRepository
import com.kq.acdos.data.remote.CrewMessageCreateDto
import com.kq.acdos.data.remote.CrewMessageDto
import com.kq.acdos.data.remote.CrewMessagePageDto
import com.kq.acdos.data.remote.CrewMessageReadDto
import com.kq.acdos.data.remote.MessageReplyCreateDto
import com.kq.acdos.data.remote.MessagesApi
import com.kq.acdos.data.remote.PresetMessageDto
import com.kq.acdos.data.remote.PresetMessageListDto
import java.time.Instant
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import retrofit2.Response

private val SENT_AT: Instant = Instant.parse("2026-11-16T03:00:00Z")

private fun message(id: String, minutes: Long = 0): CrewMessageDto {
    val sentAt = SENT_AT.plusSeconds(minutes * 60)
    return CrewMessageDto(id, "crew-$id", "Crew $id", "late", "Late", sentAt, null, emptyList())
}

/** The crew messages the inbox gets, and which ones the app marked read. */
class FakeInboxApi : MessagesApi {
    var inbox = listOf(message("m1"))
    val read = mutableListOf<String>()

    override suspend fun messages(cursor: String?, limit: Int?) =
        Response.success(CrewMessagePageDto(inbox, null))

    override suspend fun markRead(messageId: String): Response<CrewMessageReadDto> {
        read += messageId
        return Response.success(CrewMessageReadDto(messageId, SENT_AT))
    }

    override suspend fun presets() =
        Response.success(PresetMessageListDto(listOf(PresetMessageDto("noted", "Noted"))))

    override suspend fun send(idempotencyKey: String, body: CrewMessageCreateDto) =
        error("the dispatcher sends no messages")

    override suspend fun reply(
        messageId: String,
        idempotencyKey: String,
        body: MessageReplyCreateDto
    ) = error("not used here")
}

/**
 * Signed in, and the session never ends. The real one builds a Supabase client,
 * which fails under Robolectric, and its exception would surface in a later test.
 */
private object SignedIn : AuthRepository {
    override suspend fun accessToken(): String? = null

    override suspend fun refreshAccessToken(): String? = null

    override suspend fun storedSessionUserId() = "dispatcher-1"

    override suspend fun signIn(email: String, password: String) = SignInResult.Success

    override suspend fun fetchProfile() = ProfileResult.Missing

    override suspend fun signOut() = Unit

    override val sessionEnded: Flow<Unit> = MutableSharedFlow()
}

/** The real container with a fake inbox and no dispatch API, so nothing reaches a server. */
class FakeInboxApplication : AcdosApplication() {
    val api = FakeInboxApi()

    override val container: AppContainer by lazy {
        object : AppContainer(this) {
            override val authRepository: AuthRepository = SignedIn

            override val messagesRepository by lazy {
                MessagesRepository(api, database.crewDao())
            }

            override val dispatchRepository: DispatchRepository? = null
        }
    }
}

/** The dispatcher's bottom nav (#230), on the real activity. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = FakeInboxApplication::class)
class DispatcherTabsTest {
    private val api get() = ApplicationProvider.getApplicationContext<FakeInboxApplication>().api

    private fun idle() = shadowOf(Looper.getMainLooper()).idle()

    private fun DispatcherHomeActivity.tap(tab: DispatcherTab) {
        findViewById<BottomNavigationView>(R.id.bottom_nav).selectedItemId = tab.itemId
        idle()
    }

    private fun DispatcherHomeActivity.refresh() {
        findViewById<MaterialToolbar>(R.id.toolbar).menu
            .performIdentifierAction(R.id.action_refresh, 0)
        idle()
    }

    private fun DispatcherHomeActivity.screen(tab: DispatcherTab): Fragment? =
        supportFragmentManager.findFragmentByTag(tab.tag)
            ?.childFragmentManager?.findFragmentById(R.id.tab_screen)

    private fun start() = Robolectric.buildActivity(DispatcherHomeActivity::class.java)
        .setup()
        .get()
        .also { idle() }

    @Test
    fun messagesAreMarkedReadOnlyWhileTheMessagesTabIsShowing() {
        val activity = start()
        assertEquals("not on Overview", emptyList<String>(), api.read)

        activity.tap(DispatcherTab.MESSAGES)
        assertEquals(listOf("m1"), api.read)

        // On another tab a new message is selected (m1 has gone), but not read.
        activity.tap(DispatcherTab.OVERVIEW)
        api.inbox = listOf(message("m2", minutes = 5))
        activity.refresh()
        assertEquals(listOf("m1"), api.read)

        activity.tap(DispatcherTab.MESSAGES)
        assertEquals(listOf("m1", "m2"), api.read)
    }

    @Test
    fun aDrillDownStaysInItsTabWithItsOwnBackStack() {
        val activity = start()
        val toolbar = activity.findViewById<MaterialToolbar>(R.id.toolbar)

        activity.open(DispatcherTab.PLAN, ReplanFragment())
        idle()
        assertEquals(DispatcherTab.PLAN, activity.current)
        assertTrue(activity.screen(DispatcherTab.PLAN) is ReplanFragment)
        assertNotNull("back arrow", toolbar.navigationIcon)

        // Overview has no back arrow; Plan is still on Re-plan when it comes back.
        activity.tap(DispatcherTab.OVERVIEW)
        assertNull(toolbar.navigationIcon)
        activity.tap(DispatcherTab.PLAN)
        assertTrue(activity.screen(DispatcherTab.PLAN) is ReplanFragment)

        activity.onBackPressedDispatcher.onBackPressed()
        idle()
        assertTrue(activity.screen(DispatcherTab.PLAN) is OptimisationRunFragment)
        assertNull(toolbar.navigationIcon)

        // Back from a tab's first screen goes to Overview.
        activity.onBackPressedDispatcher.onBackPressed()
        idle()
        assertEquals(DispatcherTab.OVERVIEW, activity.current)
    }

    @Test
    fun tappingTheSelectedTabAgainGoesBackToItsFirstScreen() {
        val activity = start()
        activity.open(DispatcherTab.PLAN, ReplanFragment())
        idle()

        activity.tap(DispatcherTab.PLAN)

        assertTrue(activity.screen(DispatcherTab.PLAN) is OptimisationRunFragment)
    }
}
