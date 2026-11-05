package com.kq.acdos.ui

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.util.TypedValue
import android.view.LayoutInflater
import androidx.annotation.AttrRes
import androidx.appcompat.R as AppCompatR
import androidx.appcompat.view.ContextThemeWrapper
import androidx.core.graphics.ColorUtils
import androidx.test.core.app.ApplicationProvider
import com.google.android.material.R as MaterialR
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.google.android.material.button.MaterialButton
import com.google.android.material.chip.Chip
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.textfield.TextInputLayout
import com.kq.acdos.R
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.ParameterizedRobolectricTestRunner
import org.robolectric.ParameterizedRobolectricTestRunner.Parameters
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

private const val TEXT = 4.5
private const val COMPONENT = 3.0

/** Runs every check against the real theme, once with the light tokens and once with the dark. */
@RunWith(ParameterizedRobolectricTestRunner::class)
@Config(sdk = [35])
class ThemeTest(private val qualifier: String) {
    companion object {
        @JvmStatic
        @Parameters(name = "{0}")
        fun modes() = listOf("notnight", "night")
    }

    private val context: Context by lazy {
        RuntimeEnvironment.setQualifiers(qualifier)
        ContextThemeWrapper(ApplicationProvider.getApplicationContext(), R.style.Theme_ACDOS)
    }

    private fun color(@AttrRes attr: Int): Int {
        val value = TypedValue()
        assertTrue("attribute not set", context.theme.resolveAttribute(attr, value, true))
        return if (value.resourceId != 0) context.getColor(value.resourceId) else value.data
    }

    private val red get() = color(AppCompatR.attr.colorPrimary)

    private fun ColorStateList.at(vararg states: Int) = getColorForState(states, defaultColor)

    private fun contrast(foreground: Int, background: Int) =
        ColorUtils.calculateContrast(foreground, background)

    private fun assertReadable(name: String, foreground: Int, background: Int) {
        val ratio = contrast(foreground, background)
        assertTrue("$name is $ratio:1 in $qualifier", ratio >= TEXT)
    }

    @Test
    fun `the accent is the same red in both themes`() {
        assertEquals(Color.parseColor("#E01A22"), red)
    }

    @Test
    fun `no colour role is left on the Material baseline purple`() {
        val roles = mapOf(
            "primaryContainer" to MaterialR.attr.colorPrimaryContainer,
            "onPrimaryContainer" to MaterialR.attr.colorOnPrimaryContainer,
            "primaryInverse" to MaterialR.attr.colorPrimaryInverse,
            "primaryFixed" to MaterialR.attr.colorPrimaryFixed,
            "primaryFixedDim" to MaterialR.attr.colorPrimaryFixedDim,
            "onPrimaryFixed" to MaterialR.attr.colorOnPrimaryFixed,
            "onPrimaryFixedVariant" to MaterialR.attr.colorOnPrimaryFixedVariant,
            "secondary" to MaterialR.attr.colorSecondary,
            "onSecondary" to MaterialR.attr.colorOnSecondary,
            "secondaryContainer" to MaterialR.attr.colorSecondaryContainer,
            "onSecondaryContainer" to MaterialR.attr.colorOnSecondaryContainer,
            "secondaryFixed" to MaterialR.attr.colorSecondaryFixed,
            "secondaryFixedDim" to MaterialR.attr.colorSecondaryFixedDim,
            "onSecondaryFixed" to MaterialR.attr.colorOnSecondaryFixed,
            "onSecondaryFixedVariant" to MaterialR.attr.colorOnSecondaryFixedVariant,
            "tertiary" to MaterialR.attr.colorTertiary,
            "onTertiary" to MaterialR.attr.colorOnTertiary,
            "tertiaryContainer" to MaterialR.attr.colorTertiaryContainer,
            "onTertiaryContainer" to MaterialR.attr.colorOnTertiaryContainer,
            "tertiaryFixed" to MaterialR.attr.colorTertiaryFixed,
            "tertiaryFixedDim" to MaterialR.attr.colorTertiaryFixedDim,
            "onTertiaryFixed" to MaterialR.attr.colorOnTertiaryFixed,
            "onTertiaryFixedVariant" to MaterialR.attr.colorOnTertiaryFixedVariant,
            "background" to android.R.attr.colorBackground,
            "onBackground" to MaterialR.attr.colorOnBackground,
            "surface" to MaterialR.attr.colorSurface,
            "containerLowest" to MaterialR.attr.colorSurfaceContainerLowest,
            "containerLow" to MaterialR.attr.colorSurfaceContainerLow,
            "container" to MaterialR.attr.colorSurfaceContainer,
            "containerHigh" to MaterialR.attr.colorSurfaceContainerHigh,
            "containerHighest" to MaterialR.attr.colorSurfaceContainerHighest,
            "surfaceVariant" to MaterialR.attr.colorSurfaceVariant,
            "surfaceBright" to MaterialR.attr.colorSurfaceBright,
            "surfaceDim" to MaterialR.attr.colorSurfaceDim,
            "surfaceInverse" to MaterialR.attr.colorSurfaceInverse,
            "onSurface" to MaterialR.attr.colorOnSurface,
            "onSurfaceVariant" to MaterialR.attr.colorOnSurfaceVariant,
            "onSurfaceInverse" to MaterialR.attr.colorOnSurfaceInverse,
            "outline" to MaterialR.attr.colorOutline,
            "outlineVariant" to MaterialR.attr.colorOutlineVariant,
            "error" to AppCompatR.attr.colorError,
            "onError" to MaterialR.attr.colorOnError,
            "errorContainer" to MaterialR.attr.colorErrorContainer,
            "onErrorContainer" to MaterialR.attr.colorOnErrorContainer
        )
        for ((name, attr) in roles) {
            val hsl = FloatArray(3)
            ColorUtils.colorToHSL(color(attr), hsl)
            val purple = hsl[0] in 240f..320f && hsl[1] > 0.15f
            assertFalse("$name is purple in $qualifier", purple)
        }
    }

    @Test
    fun `text on every token surface reaches 4_5 to 1`() {
        val pairs = listOf(
            Triple("on red", MaterialR.attr.colorOnPrimary, AppCompatR.attr.colorPrimary),
            Triple(
                "accent text",
                MaterialR.attr.colorOnPrimaryContainer,
                MaterialR.attr.colorSurface
            ),
            Triple(
                "tint",
                MaterialR.attr.colorOnPrimaryContainer,
                MaterialR.attr.colorPrimaryContainer
            ),
            Triple(
                "secondary on highest",
                MaterialR.attr.colorOnSurfaceVariant,
                MaterialR.attr.colorSurfaceContainerHighest
            ),
            Triple(
                "error banner",
                MaterialR.attr.colorOnErrorContainer,
                MaterialR.attr.colorErrorContainer
            ),
            Triple(
                "warning chip",
                R.attr.colorOnWarningContainer,
                R.attr.colorWarningContainer
            ),
            Triple(
                "success chip",
                R.attr.colorOnSuccessContainer,
                R.attr.colorSuccessContainer
            ),
            Triple(
                "snackbar text",
                MaterialR.attr.colorOnSurfaceInverse,
                MaterialR.attr.colorSurfaceInverse
            ),
            Triple(
                "snackbar action",
                MaterialR.attr.colorPrimaryInverse,
                MaterialR.attr.colorSurfaceInverse
            )
        )
        for ((name, foreground, background) in pairs) {
            assertReadable(name, color(foreground), color(background))
        }
    }

    @Test
    fun `red fills stand out from every surface they sit on`() {
        val surfaces = listOf(
            android.R.attr.colorBackground,
            MaterialR.attr.colorSurface,
            MaterialR.attr.colorSurfaceContainer
        )
        for (surface in surfaces) {
            val ratio = contrast(red, color(surface))
            assertTrue("red is $ratio:1 in $qualifier", ratio >= COMPONENT)
        }
    }

    @Test
    fun `text buttons and outlined buttons are not red`() {
        val text = MaterialButton(context, null, AppCompatR.attr.borderlessButtonStyle)
        val outlined = MaterialButton(context, null, MaterialR.attr.materialButtonOutlinedStyle)

        assertEquals(color(MaterialR.attr.colorOnPrimaryContainer), text.currentTextColor)
        assertEquals(color(MaterialR.attr.colorOnSurface), outlined.currentTextColor)
    }

    @Test
    fun `a filled button is white on red`() {
        val button = MaterialButton(context)

        assertEquals(red, button.backgroundTintList!!.defaultColor)
        assertEquals(Color.WHITE, button.currentTextColor)
    }

    @Test
    fun `dialog buttons are not red`() {
        val themed = MaterialAlertDialogBuilder(context).context
        val value = TypedValue()
        themed.theme.resolveAttribute(AppCompatR.attr.buttonBarPositiveButtonStyle, value, true)
        val button = MaterialButton(themed, null, AppCompatR.attr.buttonBarPositiveButtonStyle)

        assertEquals(R.style.Widget_ACDOS_Button_Dialog, value.resourceId)
        assertEquals(color(MaterialR.attr.colorOnPrimaryContainer), button.currentTextColor)
    }

    @Test
    fun `a focused text field label and cursor are not red`() {
        val field = TextInputLayout(context)
        val focused = intArrayOf(android.R.attr.state_enabled, android.R.attr.state_focused)
        val accent = color(MaterialR.attr.colorOnPrimaryContainer)

        assertEquals(accent, field.hintTextColor!!.at(*focused))
        assertEquals(accent, field.cursorColor!!.defaultColor)
    }

    @Test
    fun `the selected tab is red with a white icon`() {
        val nav = LayoutInflater.from(context)
            .inflate(R.layout.activity_driver_home, null)
            .findViewById<BottomNavigationView>(R.id.bottom_nav)
        val checked = intArrayOf(android.R.attr.state_checked)

        assertEquals(red, nav.itemActiveIndicatorColor!!.defaultColor)
        assertEquals(Color.WHITE, nav.itemIconTintList!!.at(*checked))
        assertEquals(
            color(MaterialR.attr.colorOnPrimaryContainer),
            nav.itemTextColor!!.at(*checked)
        )
    }

    @Test
    fun `status chips use the status tokens`() {
        val row = LayoutInflater.from(context).inflate(R.layout.fragment_route, null)
        val warned = row.findViewById<Chip>(R.id.status_warning)

        assertEquals(color(R.attr.colorWarningContainer), warned.chipBackgroundColor!!.defaultColor)
        assertEquals(color(R.attr.colorOnWarningContainer), warned.currentTextColor)
    }
}

/** Reads the layout sources, so a screen can't quietly go around the theme. */
class ThemeSourceRulesTest {
    private val res = File("src/main/res")
    private val rawHex = Regex("#[0-9a-fA-F]{3,8}\\b")
    private val textOnRed =
        Regex("""(textColor|TextColor|textColorHint|textColorLink)[^>\n]*colorPrimary["<]""")

    private fun files(vararg folders: String) = folders.flatMap { folder ->
        File(res, folder).listFiles().orEmpty().filter { it.extension == "xml" }
    }

    @Test
    fun `layouts never pick a raw colour`() {
        assertTrue(res.isDirectory)
        for (file in files("layout", "menu")) {
            assertFalse("${file.name} has a raw colour", rawHex.containsMatchIn(file.readText()))
        }
    }

    @Test
    fun `no text is coloured with colorPrimary`() {
        for (file in files("layout", "values", "color")) {
            assertFalse("${file.name} colours text red", textOnRed.containsMatchIn(file.readText()))
        }
    }
}
