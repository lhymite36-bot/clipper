plugins {
    id("org.jetbrains.kotlin.jvm")
    application
}
java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}
kotlin {
    jvmToolchain(17)
}
application {
    mainClass.set("app.clipper.pipeline.RenderSample")
}
dependencies {
    implementation("org.json:json:20240303")
    testImplementation("org.junit.jupiter:junit-jupiter:5.11.3")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}
tasks.test {
    useJUnitPlatform()
    testLogging { showStandardStreams = System.getenv("LIVE_FETCH") == "1" }
    if (System.getenv("LIVE_FETCH") == "1") outputs.upToDateWhen { false }
}
tasks.register<JavaExec>("runSample") {
    group = "application"
    classpath = sourceSets["main"].runtimeClasspath
    mainClass.set("app.clipper.pipeline.RenderSample")
    val pass = listOf("sampleSource", "sampleOut", "sampleFonts", "sampleWork", "sampleTranscript", "sampleUrl", "sampleLabel", "sampleLicense")
    pass.forEach { key ->
        if (project.hasProperty(key)) systemProperty(key, project.property(key).toString())
    }
}
