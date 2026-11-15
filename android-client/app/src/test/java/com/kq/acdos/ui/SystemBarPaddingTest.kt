package com.kq.acdos.ui

import android.content.Context
import android.view.View
import android.widget.LinearLayout
import androidx.core.graphics.Insets
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class SystemBarPaddingTest {
    private val context = ApplicationProvider.getApplicationContext<Context>()

    private fun insets(statusBar: Int, navBar: Int, keyboard: Int = 0) =
        WindowInsetsCompat.Builder()
            .setInsets(WindowInsetsCompat.Type.statusBars(), Insets.of(0, statusBar, 0, 0))
            .setInsets(WindowInsetsCompat.Type.navigationBars(), Insets.of(0, 0, 0, navBar))
            .setInsets(WindowInsetsCompat.Type.ime(), Insets.of(0, 0, 0, keyboard))
            .build()

    @Test
    fun `with a bottom bar the bar takes the nav inset and root takes none`() {
        val root = LinearLayout(context)
        val bar = View(context)
        root.addView(bar)
        applySystemBarPadding(root, bar)

        ViewCompat.dispatchApplyWindowInsets(root, insets(statusBar = 63, navBar = 126))

        assertEquals(63, root.paddingTop)
        assertEquals(0, root.paddingBottom)
        assertEquals(126, bar.paddingBottom)
    }

    @Test
    fun `insets stop at root so the bottom nav cannot pad itself a second time`() {
        val root = LinearLayout(context)
        val bar = View(context)
        root.addView(bar)
        var barSawInsets = false
        // Stands in for BottomNavigationView's own bottom-inset listener.
        ViewCompat.setOnApplyWindowInsetsListener(bar) { _, insets ->
            barSawInsets = true
            insets
        }
        applySystemBarPadding(root, bar)

        ViewCompat.dispatchApplyWindowInsets(root, insets(statusBar = 63, navBar = 126))

        assertFalse(barSawInsets)
    }

    @Test
    fun `with the keyboard up root takes the keyboard and the bar takes nothing`() {
        val root = LinearLayout(context)
        val bar = View(context)
        root.addView(bar)
        applySystemBarPadding(root, bar)

        ViewCompat.dispatchApplyWindowInsets(root, insets(63, 126, keyboard = 800))

        assertEquals(800, root.paddingBottom)
        assertEquals(0, bar.paddingBottom)
    }

    @Test
    fun `without a bottom bar root takes every inset`() {
        val root = LinearLayout(context)
        applySystemBarPadding(root)

        ViewCompat.dispatchApplyWindowInsets(root, insets(statusBar = 63, navBar = 126))

        assertEquals(63, root.paddingTop)
        assertEquals(126, root.paddingBottom)
    }
}
