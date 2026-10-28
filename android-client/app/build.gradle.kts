plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.ksp)
}

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
}
