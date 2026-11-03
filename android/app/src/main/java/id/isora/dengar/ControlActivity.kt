package id.isora.dengar

import android.annotation.SuppressLint
import android.annotation.TargetApi
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.graphics.Color
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView

/**
 * The glasses' own control pages inside this app, so the person never has to
 * open a browser and type an address the app already knows.
 *
 * WebView follows the process's default network, which on a WiFi without
 * internet is mobile data — where the glasses are not. So the process is bound
 * to the glasses' network for as long as this screen is open. [ListenService]
 * in the same process is unaffected: it already connects on that network.
 */
class ControlActivity : Activity() {

    private lateinit var web: WebView
    private var host = ""
    private var address = ""
    private var startUrl = ""
    private var boundProcess = false

    @SuppressLint("SetJavaScriptEnabled") // the page is the glasses' own, on the local network
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        address = intent.getStringExtra(EXTRA_ADDRESS) ?: return finish()
        host = address.substringBefore(':')
        startUrl = "http://$address${intent.getStringExtra(EXTRA_PATH) ?: "/"}"

        web = try {
            WebView(this)
        } catch (e: RuntimeException) {
            // No usable WebView on this phone (disabled, mid-update): the browser
            // still gets the person to the same page.
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(startUrl)))
            return finish()
        }
        bindToGlassesNetwork()

        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true // the page keeps its token and contrast choice there
        web.settings.mediaPlaybackRequiresUserGesture = false
        web.webViewClient = Client()

        // The page gets the whole screen, exactly as in a browser; the way back
        // is a small pill floating in a corner (and the phone's own Back).
        val back = TextView(this).apply {
            setText(R.string.control_back)
            contentDescription = getString(R.string.control_back_full)
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setBackgroundResource(R.drawable.btn_float)
            gravity = Gravity.CENTER
            minHeight = dp(44)
            setPadding(dp(16), 0, dp(16), 0)
            isClickable = true
            isFocusable = true
            setOnClickListener { finish() }
        }
        val root = FrameLayout(this).apply {
            id = View.generateViewId()
            addView(web, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
            addView(back, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM or Gravity.START).apply { setMargins(dp(12), dp(12), dp(12), dp(16)) })
        }
        setContentView(root)
        if (Build.VERSION.SDK_INT >= 35) applyInsets(root)
        web.loadUrl(startUrl)
    }

    private fun bindToGlassesNetwork() {
        val network = Net.networkFor(this, host) ?: return
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        boundProcess = cm.bindProcessToNetwork(network)
    }

    override fun onDestroy() {
        if (::web.isInitialized) web.destroy()
        if (boundProcess) {
            (getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager).bindProcessToNetwork(null)
        }
        super.onDestroy()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (::web.isInitialized && web.canGoBack()) {
            web.goBack()
        } else {
            @Suppress("DEPRECATION")
            super.onBackPressed()
        }
    }

    private inner class Client : WebViewClient() {

        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            val url = request.url
            if (url.host != host) {
                // A link off the glasses (docs, the cloud app): a real browser's job.
                startActivity(Intent(Intent.ACTION_VIEW, url))
                return true
            }
            if (url.path?.trimEnd('/') == "/dengar") {
                // "Listen on this phone" — this app is that, and a second player in a
                // WebView would fight the service over the same long-poll.
                ListenService.start(this@ControlActivity)
                finish()
                return true
            }
            return false
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            if (!request.isForMainFrame) return
            val page = getString(R.string.control_failed, Address.display(address), error.description, startUrl)
            view.loadDataWithBaseURL(startUrl, page, "text/html", "utf-8", startUrl)
        }
    }

    @TargetApi(35)
    private fun applyInsets(root: View) {
        root.setOnApplyWindowInsetsListener { v, insets ->
            val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    companion object {
        private const val EXTRA_ADDRESS = "address"
        private const val EXTRA_PATH = "path"
        const val PATH_CONTROL = "/"

        fun open(context: Context, address: String, path: String) {
            context.startActivity(
                Intent(context, ControlActivity::class.java)
                    .putExtra(EXTRA_ADDRESS, address)
                    .putExtra(EXTRA_PATH, path),
            )
        }
    }
}
