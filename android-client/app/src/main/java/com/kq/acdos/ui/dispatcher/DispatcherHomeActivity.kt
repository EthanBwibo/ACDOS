package com.kq.acdos.ui.dispatcher

import android.os.Bundle
import android.view.View
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.commit
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.progressindicator.LinearProgressIndicator
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import com.kq.acdos.ui.applySystemBarPadding
import com.kq.acdos.ui.openLoginWhenSessionEnds
import com.kq.acdos.ui.showStatusBanners
import com.kq.acdos.ui.showThemeDialog
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * The dispatcher's app (#27): the hub, and a screen each for what it drills
 * down to (Figma section 1). No bottom nav: back always returns to the hub.
 * All the screens share these ViewModels, so a job started on one keeps
 * running on the others. Online only: nothing here is cached.
 */
class DispatcherHomeActivity : AppCompatActivity() {
    private val container by lazy { (application as AcdosApplication).container }
    private val viewModel: DispatcherViewModel by viewModels { DispatcherViewModel.Factory }
    private val inbox: InboxViewModel by viewModels { InboxViewModel.Factory }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_dispatcher_home)
        val root = findViewById<View>(R.id.main)
        applySystemBarPadding(root)

        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        toolbar.setNavigationOnClickListener { supportFragmentManager.popBackStack() }
        toolbar.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                R.id.action_refresh -> {
                    viewModel.load()
                    inbox.load()
                    true
                }

                R.id.action_theme -> {
                    showThemeDialog(container.themeStore)
                    true
                }

                R.id.action_sign_out -> {
                    lifecycleScope.launch { container.sessionRouter.signOut() }
                    true
                }

                else -> false
            }
        }
        supportFragmentManager.addOnBackStackChangedListener { showBackArrow(toolbar) }
        showBackArrow(toolbar)
        // After a rotation the FragmentManager restores the open screen by itself.
        if (savedInstanceState == null) {
            supportFragmentManager.commit { replace(R.id.screen, DispatchHubFragment()) }
        }

        val loading = findViewById<LinearProgressIndicator>(R.id.loading)
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(viewModel.state, inbox.loading) { state, inboxLoading ->
                    state.loading || inboxLoading
                }.collect { loading.isVisible = it }
            }
        }
        val failure = combine(viewModel.state, inbox.loadFailed) { state, inboxFailed ->
            state.loadFailure?.let { getString(it.text, it.detail) }
                ?: getString(R.string.dispatch_inbox_failed).takeIf { inboxFailed }
        }
        showStatusBanners(container, R.string.dispatch_offline_banner, failure)
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.messages.collect { message ->
                    val text = getString(message.text, message.detail)
                    Snackbar.make(root, text, Snackbar.LENGTH_LONG).show()
                }
            }
        }

        openLoginWhenSessionEnds(container)
    }

    private fun showBackArrow(toolbar: MaterialToolbar) {
        val drilledDown = supportFragmentManager.backStackEntryCount > 0
        if (drilledDown) {
            toolbar.setNavigationIcon(R.drawable.ic_arrow_back)
        } else {
            toolbar.navigationIcon = null
        }
    }

    /** Each screen names itself, including when a rotation restores it. */
    fun showTitle(title: String) {
        findViewById<MaterialToolbar>(R.id.toolbar).title = title
    }

    fun open(screen: Fragment) {
        supportFragmentManager.commit {
            replace(R.id.screen, screen)
            addToBackStack(null)
        }
    }

    fun close() {
        supportFragmentManager.popBackStack()
    }
}
