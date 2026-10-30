package com.kq.acdos.ui

import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.activity.enableEdgeToEdge
import androidx.annotation.StringRes
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.kq.acdos.AcdosApplication
import com.kq.acdos.R
import kotlinx.coroutines.launch

/**
 * Stand-in home screen until the real role screens land (#27 dispatcher,
 * #56 crew). Shows who is signed in and offers sign-out.
 */
abstract class PlaceholderHomeActivity(@StringRes private val roleLabel: Int) :
    AppCompatActivity() {
    private val container by lazy { (application as AcdosApplication).container }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_home_placeholder)
        applySystemBarPadding(findViewById(R.id.main))

        findViewById<TextView>(R.id.full_name).text =
            intent.getStringExtra(EXTRA_FULL_NAME).orEmpty()
        findViewById<TextView>(R.id.role).setText(roleLabel)

        // Sign-out only ends the session; the collector below does the navigating.
        val signOut = findViewById<Button>(R.id.sign_out)
        signOut.setOnClickListener {
            signOut.isEnabled = false
            lifecycleScope.launch { container.sessionRouter.signOut() }
        }

        openLoginWhenSessionEnds(container)
    }
}

class CrewHomeActivity : PlaceholderHomeActivity(R.string.role_crew)

class DispatcherHomeActivity : PlaceholderHomeActivity(R.string.role_dispatcher)
