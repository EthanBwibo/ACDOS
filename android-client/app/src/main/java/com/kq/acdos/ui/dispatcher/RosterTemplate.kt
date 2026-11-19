package com.kq.acdos.ui.dispatcher

import android.content.Context
import android.net.Uri
import android.widget.Toast
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.kq.acdos.R
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * The roster template's file name (#254): the headers the import expects and two example
 * rows. The app bundles it as an asset, a copy of docs/acdos_roster_template.csv, which
 * RosterTemplateTest keeps the same.
 */
internal const val ROSTER_TEMPLATE = "acdos_roster_template.csv"

/**
 * Copies the bundled template to [uri]. True when it was written; false when the place
 * the dispatcher picked can't be written to.
 */
internal fun saveRosterTemplate(context: Context, uri: Uri): Boolean = try {
    val out = context.contentResolver.openOutputStream(uri) ?: throw IOException("no stream")
    out.use { target -> context.assets.open(ROSTER_TEMPLATE).use { it.copyTo(target) } }
    true
} catch (e: IOException) {
    false
} catch (e: SecurityException) {
    false
}

/**
 * Download template: the system file picker (SAF) asks where to save it, so no storage
 * permission is needed. Made as a property, so it is registered before the fragment is
 * created, as the Activity Result API requires.
 */
internal fun Fragment.rosterTemplateSaver(): ActivityResultLauncher<String> =
    registerForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri ->
        uri ?: return@registerForActivityResult
        val context = requireContext().applicationContext
        viewLifecycleOwner.lifecycleScope.launch {
            val saved = withContext(Dispatchers.IO) { saveRosterTemplate(context, uri) }
            val text = if (saved) {
                R.string.roster_template_saved
            } else {
                R.string.roster_template_failed
            }
            Toast.makeText(context, text, Toast.LENGTH_LONG).show()
        }
    }
