import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.ksp)
    alias(libs.plugins.kotlin.serialization)
}

// Supabase project URL and publishable key come from local.properties (not in git),
// or from environment variables. CI builds without them: the app then shows
// "not configured" instead of signing in.
val localProperties = Properties().apply {
    providers.fileContents(rootProject.layout.projectDirectory.file("local.properties"))
        .asText.orNull?.let { load(it.reader()) }
}

fun supabaseSetting(property: String, env: String): String =
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

        val supabaseUrl = supabaseSetting("supabase.url", "SUPABASE_URL")
        val supabaseKey = supabaseSetting("supabase.publishableKey", "SUPABASE_PUBLISHABLE_KEY")
        buildConfigField("String", "SUPABASE_URL", "\"$supabaseUrl\"")
        buildConfigField("String", "SUPABASE_PUBLISHABLE_KEY", "\"$supabaseKey\"")
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
    // Moshi adapters generated at compile time (KSP), so no kotlin-reflect in the APK
    implementation(libs.moshi)
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
