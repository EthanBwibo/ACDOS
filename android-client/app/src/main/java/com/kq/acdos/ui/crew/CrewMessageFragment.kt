package com.kq.acdos.ui.crew

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.button.MaterialButton
import com.google.android.material.snackbar.Snackbar
import com.kq.acdos.R
import kotlinx.coroutines.launch

/**
 * Messages to the dispatcher (#57): one button per preset. There is no text
 * field anywhere: crew can only send a preset, and only to the dispatcher.
 */
class CrewMessageFragment : Fragment(R.layout.fragment_crew_message) {
    private val viewModel: CrewMessageViewModel by viewModels { CrewMessageViewModel.Factory }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        val list = view.findViewById<LinearLayout>(R.id.presets)
        val empty = view.findViewById<TextView>(R.id.empty)

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.presets.collect { presets ->
                    list.removeAllViews()
                    empty.isVisible = presets.isEmpty()
                    for (preset in presets) {
                        val button = MaterialButton(requireContext()).apply {
                            text = preset.label
                            isEnabled = !viewModel.sending.value
                            setOnClickListener { viewModel.send(preset.code) }
                        }
                        list.addView(button)
                    }
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.sending.collect { sending ->
                    for (i in 0 until list.childCount) {
                        (list.getChildAt(i) as Button).isEnabled = !sending
                    }
                }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                viewModel.messages.collect { message ->
                    Snackbar.make(view, message, Snackbar.LENGTH_LONG).show()
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        viewModel.refresh()
    }
}
