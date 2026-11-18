package com.kq.acdos.ui.dispatcher

import com.kq.acdos.R
import com.kq.acdos.data.DispatchRepository
import com.kq.acdos.data.remote.DispatcherApi
import com.kq.acdos.data.remote.OptimisationJobsApi
import com.kq.acdos.data.remote.RejectReasonDto
import com.kq.acdos.data.remote.RosterImportResultDto
import java.io.IOException
import java.time.LocalDate
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Response

/** Import roster (#229): a dry run first, then the import with one key per file. */
@OptIn(ExperimentalCoroutinesApi::class)
class RosterImportViewModelTest {
    private val csv = "staff_no,name\nKQ1,Amina\n".toByteArray()

    /** What the app sent: dry run or not, the key, the file's name and its text. */
    private data class Sent(
        val dryRun: Boolean,
        val key: String?,
        val name: String,
        val text: String
    )

    private class FakeApi : DispatcherApi {
        val sent = mutableListOf<Sent>()
        var pickups = 2
        var failNext = false

        /** The next answer is this HTTP error, e.g. 422 for a file with the wrong columns. */
        var errorNext: Int? = null
        var contentType: String? = null

        override suspend fun importRoster(
            file: MultipartBody.Part,
            dryRun: Boolean,
            idempotencyKey: String?
        ): Response<RosterImportResultDto> {
            val text = Buffer().also { file.body.writeTo(it) }.readUtf8()
            val disposition = file.headers?.get("Content-Disposition").orEmpty()
            val name = Regex("filename=\"([^\"]*)\"").find(disposition)?.groupValues?.get(1)
            contentType = file.body.contentType()?.toString()
            sent += Sent(dryRun, idempotencyKey, name.orEmpty(), text)
            if (failNext) {
                failNext = false
                throw IOException("no signal")
            }
            errorNext?.let { status ->
                errorNext = null
                val body = """{"code":"VALIDATION_FAILED","detail":"No staff_no column"}"""
                return Response.error(status, body.toResponseBody("application/json".toMediaType()))
            }
            return Response.success(
                RosterImportResultDto(dryRun, pickups + 1, 1, 1, pickups, 1, emptyList())
            )
        }

        override suspend fun pickups(date: LocalDate?, cursor: String?, limit: Int?) =
            error("not used here")

        override suspend fun vehicles(cursor: String?, limit: Int?) = error("not used here")

        override suspend fun crew(query: String?, cursor: String?, limit: Int?) =
            error("not used here")

        override suspend fun nearestZone(lat: Double, lon: Double) = error("not used here")

        override suspend fun addPickup(
            idempotencyKey: String,
            body: com.kq.acdos.data.remote.PickupRequestCreateDto
        ) = error("not used here")

        override suspend fun setHome(
            crewMemberId: String,
            body: com.kq.acdos.data.remote.LatLonDto
        ) = error("not used here")

        override suspend fun routes(date: LocalDate?, cursor: String?, limit: Int?) =
            error("not used here")

        override suspend fun setReportTime(
            pickupId: String,
            update: com.kq.acdos.data.remote.PickupReportTimeUpdateDto
        ) = error("not used here")

        override suspend fun setVehicleStatus(
            vehicleId: String,
            update: com.kq.acdos.data.remote.VehicleStatusUpdateDto
        ) = error("not used here")
    }

    private val noJobs = object : OptimisationJobsApi {
        override suspend fun createJob(
            idempotencyKey: String,
            body: com.kq.acdos.data.remote.OptimisationJobCreateDto
        ) = error("not used here")

        override suspend fun getJob(jobId: String) = error("not used here")
    }

    private val api = FakeApi()
    private var keys = 0
    private val viewModel = RosterImportViewModel(
        DispatchRepository(api, noJobs),
        newKey = { "key-${++keys}" }
    )

    @Before
    fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher())

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun choosingAFile_runsADryRunWithNoKey() {
        viewModel.choose("roster.csv", csv)

        assertEquals(listOf(Sent(true, null, "roster.csv", String(csv))), api.sent)
        assertEquals("text/csv", api.contentType)
        val state = viewModel.state.value
        assertEquals(2, state.check?.pickupsCreated)
        assertNull(state.imported)
        assertTrue(state.canImport)
    }

    @Test
    fun importing_sendsTheSameFileWithAKey() {
        viewModel.choose("roster.csv", csv)

        viewModel.importNow()

        assertEquals(Sent(false, "key-1", "roster.csv", String(csv)), api.sent.last())
        assertEquals(false, viewModel.state.value.imported?.dryRun)
        assertFalse("imported once", viewModel.state.value.canImport)
    }

    @Test
    fun aFailedImport_isRetriedWithTheSameKey() {
        viewModel.choose("roster.csv", csv)
        api.failNext = true

        viewModel.importNow()
        assertEquals(R.string.dispatch_offline, viewModel.state.value.failure?.text)
        assertNull(viewModel.state.value.imported)

        viewModel.retry()

        assertEquals(listOf("key-1", "key-1"), api.sent.drop(1).map { it.key })
        assertNull(viewModel.state.value.failure)
        assertEquals(2, viewModel.state.value.imported?.pickupsCreated)
    }

    @Test
    fun aFailedDryRun_isRetriedAsADryRun() {
        api.failNext = true
        viewModel.choose("roster.csv", csv)

        viewModel.retry()

        assertEquals(listOf(true, true), api.sent.map { it.dryRun })
        assertTrue(viewModel.state.value.canImport)
    }

    @Test
    fun anotherFile_getsANewKey() {
        viewModel.choose("monday.csv", csv)
        viewModel.importNow()

        viewModel.choose("tuesday.csv", csv)
        viewModel.importNow()

        assertEquals(listOf("key-1", "key-2"), api.sent.filterNot { it.dryRun }.map { it.key })
        assertEquals("tuesday.csv", api.sent.last().name)
    }

    @Test
    fun withNothingToImport_theImportIsNotOffered() {
        api.pickups = 0
        viewModel.choose("roster.csv", csv)

        viewModel.importNow()

        assertFalse(viewModel.state.value.canImport)
        assertEquals("only the dry run", 1, api.sent.size)
    }

    @Test
    fun aFileOverTheLimit_isRefusedWithoutSendingIt() {
        viewModel.choose("huge.csv", ByteArray(ROSTER_MAX_BYTES + 1))
        viewModel.retry()

        assertEquals(R.string.roster_too_large, viewModel.state.value.failure?.text)
        assertTrue(api.sent.isEmpty())
    }

    @Test
    fun aFileError_offersAnotherFileAndNoRetry() {
        api.errorNext = 422
        viewModel.choose("roster.csv", csv)

        val state = viewModel.state.value
        assertNotNull(state.failure)
        assertFalse("no Retry for a 422", state.showRetry)
        assertTrue("Choose another file leads", state.fileRefused)

        viewModel.retry()
        assertEquals("retry sends nothing", 1, api.sent.size)
    }

    @Test
    fun aServerError_offersRetry() {
        api.errorNext = 503
        viewModel.choose("roster.csv", csv)

        assertTrue(viewModel.state.value.showRetry)
        assertFalse(viewModel.state.value.fileRefused)
    }

    @Test
    fun noConnection_offersRetry() {
        api.failNext = true
        viewModel.choose("roster.csv", csv)

        assertTrue(viewModel.state.value.showRetry)
        assertFalse(viewModel.state.value.fileRefused)
    }

    @Test
    fun aFileOverTheLimit_offersAnotherFileAndNoRetry() {
        viewModel.choose("huge.csv", ByteArray(ROSTER_MAX_BYTES + 1))

        assertFalse(viewModel.state.value.showRetry)
        assertTrue(viewModel.state.value.fileRefused)
    }

    @Test
    fun rejectedRows_haveALabelForEveryReason() {
        val labels = RejectReasonDto.entries.map(::rejectReasonLabel).toSet()

        assertEquals(RejectReasonDto.entries.size, labels.size)
    }
}
