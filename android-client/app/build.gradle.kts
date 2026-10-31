import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.ksp)
    alias(libs.plugins.kotlin.serialization)
}

// Supabase project URL, publishable key and the API base URL come from local.properties
// (not in git), or from environment variables. CI builds without them: the app then shows
// "not configured" instead of signing in.
val localProperties = Properties().apply {
    providers.fileContents(rootProject.layout.projectDirectory.file("local.properties"))
        .asText.orNull?.let { load(it.reader()) }
}

fun localSetting(property: String, env: String): String =
    localProperties.getProperty(property) ?: providers.environmentVariable(env).orNull ?: ""

android {
    namespace = "com.kq.acdos"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.kq.acdos"
        minSdk = 26
        targetSdk = 37
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        val supabaseUrl = localSetting("supabase.url", "SUPABASE_URL")
        val supabaseKey = localSetting("supabase.publishableKey", "SUPABASE_PUBLISHABLE_KEY")
        buildConfigField("String", "SUPABASE_URL", "\"$supabaseUrl\"")
        buildConfigField("String", "SUPABASE_PUBLISHABLE_KEY", "\"$supabaseKey\"")
        val apiBaseUrl = localSetting("api.baseUrl", "API_BASE_URL")
        buildConfigField("String", "API_BASE_URL", "\"$apiBaseUrl\"")
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    // OpenApiContractTest reads the backend's contract. Declared as an input so
    // a changed spec reruns the tests instead of reusing an up-to-date result.
    testOptions {
        unitTests.all {
            val spec = rootProject.file("../docs/openapi.json")
            it.inputs.file(spec)
                .withPropertyName("openapi")
                .withPathSensitivity(PathSensitivity.RELATIVE)
            it.systemProperty("acdos.openapi", spec.absolutePath)
        }
    }
}

// Room writes each schema version as JSON here; committed, so schema changes show in review.
ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

dependencies {
    implementation(libs.androidx.activity.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.androidx.core.ktx)
    implementation(libs.material)
    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
    ksp(libs.androidx.room.compiler)
    testImplementation(libs.robolectric)
    testImplementation(libs.androidx.test.core.ktx)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.retrofit)
    implementation(libs.retrofit.converter.moshi)
    implementation(libs.okhttp)
    testImplementation(libs.okhttp.mockwebserver)
    // Moshi adapters generated at compile time (KSP), so no kotlin-reflect in the APK
    implementation(libs.moshi)
    implementation(libs.moshi.adapters)
    ksp(libs.moshi.kotlin.codegen)
    // ViewModel + lifecycleScope: coroutines tied to screen lifecycle
    implementation(libs.androidx.lifecycle.viewmodel.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    // Fragments for the bottom-nav tabs (Driver: Route/Schedule/Sync, Crew: Pickup/Message)
    implementation(libs.androidx.fragment.ktx)
    testImplementation(libs.kotlinx.coroutines.test)
    kspTest(libs.moshi.kotlin.codegen)
    // Supabase Auth (sign-in, token refresh) and PostgREST (reading profiles.role).
    // Only used behind auth.AuthRepository; the FastAPI client (#26) stays on Retrofit.
    implementation(platform(libs.supabase.bom))
    implementation(libs.supabase.auth)
    implementation(libs.supabase.postgrest)
    implementation(platform(libs.ktor.bom))
    implementation(libs.ktor.client.okhttp)
}
