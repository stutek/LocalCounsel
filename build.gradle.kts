import java.net.Socket
import java.nio.file.Files
import java.nio.file.Paths

plugins {
    kotlin("jvm") version "2.1.10"
    application
    id("de.undercouch.download") version "5.6.0"
}

group = "com.compliance"
version = "1.0-SNAPSHOT"

kotlin {
    jvmToolchain(21) // Force Gradle to use Java 21 (matching IntelliJ's stable runtime) to avoid JDK 25+ errors
}

repositories {
    mavenCentral()
}

dependencies {
    // Core LangChain4j
    implementation("dev.langchain4j:langchain4j:0.29.1")
    
    // OpenAI client (used to connect to local llama.cpp server which has an OpenAI-compatible API)
    implementation("dev.langchain4j:langchain4j-open-ai:0.29.1")
    
    // Logging
    implementation("org.slf4j:slf4j-simple:2.0.12")
    
    // Testing
    testImplementation(kotlin("test"))
}

application {
    mainClass.set("com.compliance.AssistantKt")
}

val downloadDir = layout.buildDirectory.dir("downloads")
val modelFile = downloadDir.get().file("gemma-2-2b-it-Q4_K_M.gguf")
val llamaTar = downloadDir.get().file("llama.tar.gz")
val llamaDir = layout.buildDirectory.dir("llama_cpp")
val anythingLlmAppImage = downloadDir.get().file("AnythingLLMDesktop.AppImage")

tasks.register<de.undercouch.gradle.tasks.download.Download>("downloadModel") {
    src("https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q4_K_M.gguf")
    dest(modelFile.asFile)
    overwrite(false)
}

tasks.register<de.undercouch.gradle.tasks.download.Download>("downloadLlamaCpp") {
    src("https://github.com/ggml-org/llama.cpp/releases/download/b9487/llama-b9487-bin-ubuntu-x64.tar.gz")
    dest(llamaTar.asFile)
    overwrite(false)
}

tasks.register<Copy>("extractLlamaCpp") {
    dependsOn("downloadLlamaCpp")
    from(tarTree(resources.gzip(llamaTar.asFile)))
    into(llamaDir)
    
    doLast {
        // CROSS-PLATFORM WORKAROUND: Gradle's tarTree fails to extract symlinks properly,
        // writing them as 0-byte corrupted files. We fix this neutrally using pure Kotlin
        // by finding the actual compiled binary and copying it over the broken symlinks!
        val soFiles = fileTree(llamaDir).matching { include("**/*.so*") }.files
        val groups = soFiles.groupBy { it.name.substringBefore(".so") + ".so" }
        
        for ((baseName, files) in groups) {
            // Find the actual compiled library (the largest file in the group)
            val realLibrary = files.maxByOrNull { it.length() }
            if (realLibrary != null && realLibrary.length() > 1000) {
                for (symlink in files) {
                    if (symlink != realLibrary) {
                        symlink.delete() // Remove the 0-byte corrupted file
                        try {
                            // Try creating a true symlink first (closer to original intent)
                            Files.createSymbolicLink(
                                symlink.toPath(),
                                Paths.get(realLibrary.name)
                            )
                        } catch (e: Exception) {
                            // Documented Fallback: Windows by default requires Administrator privileges 
                            // or Developer Mode to create symbolic links. If the OS rejects the symlink 
                            // creation, we log a warning and safely fallback to hard-copying the file.
                            println("⚠️  Warning: OS rejected symlink creation for \${symlink.name} (likely missing privileges). Falling back to copying file. Error: \${e.message}")
                            realLibrary.copyTo(symlink, overwrite = true)
                        }
                    }
                }
            }
        }
    }
}

tasks.register<de.undercouch.gradle.tasks.download.Download>("downloadAnythingLLM") {
    src("https://cdn.anythingllm.com/latest/AnythingLLMDesktop.AppImage")
    dest(anythingLlmAppImage.asFile)
    overwrite(false)
}

tasks.register<Exec>("chmodAnythingLLM") {
    dependsOn("downloadAnythingLLM")
    commandLine("chmod", "+x", anythingLlmAppImage.asFile.absolutePath)
}

tasks.register("provision") {
    group = "AI Assistant"
    description = "Idempotently downloads and extracts all necessary models and binaries."
    dependsOn("downloadModel", "extractLlamaCpp", "chmodAnythingLLM")
}

tasks.register("bootLlm") {
    group = "AI Assistant"
    description = "Boots the LLM server asynchronously and waits for it to be ready."
    dependsOn("provision")
    
    doLast {
        val llamaServer = fileTree(llamaDir).matching { include("**/llama-server", "**/server") }.files.firstOrNull()
            ?: throw GradleException("llama-server binary not found!")
            
        println("Starting llama-server...")
        val llmPb = ProcessBuilder(
            llamaServer.absolutePath, 
            "-m", modelFile.asFile.absolutePath, 
            "--port", "8080", 
            "--host", "127.0.0.1"
        )
        // Stream logs directly to the console for perfectly sequential debuggability
        llmPb.inheritIO()
        val llmProcess = llmPb.start()
        
        // Save the PID so it can be explicitly stopped later by the stopLlm task
        layout.buildDirectory.file("llama.pid").get().asFile.writeText(llmProcess.pid().toString())
        
        // Ensure server is killed when Gradle finishes
        Runtime.getRuntime().addShutdownHook(Thread { llmProcess.destroy() })

        print("Waiting for LLM server to bind to port 8080 ")
        var isReady = false
        for (i in 1..60) {
            try {
                Socket("127.0.0.1", 8080).use { isReady = true }
                break
            } catch (e: Exception) {
                print(".")
                Thread.sleep(1000)
            }
        }
        println()
        
        if (!isReady) {
            llmProcess.destroy()
            throw GradleException("LLM server failed to start on port 8080.")
        }
        println("✅ LLM Server is online!")
    }
}

tasks.register("stopLlm") {
    group = "AI Assistant"
    description = "Forcefully stops the LLM server (Llama + Gemma) and cleans up resources."
    
    doLast {
        val pidFile = layout.buildDirectory.file("llama.pid").get().asFile
        if (pidFile.exists()) {
            val pid = pidFile.readText().trim().toLongOrNull()
            if (pid != null) {
                // Use Java 9+ ProcessHandle for purely cross-platform, OS-agnostic process killing!
                ProcessHandle.of(pid).ifPresentOrElse(
                    { process -> 
                        println("🛑 Stopping LLM server (PID: \$pid) and all child processes...")
                        // Ensure all child processes spawned by the server are also killed
                        process.descendants().forEach { it.destroyForcibly() }
                        process.destroyForcibly() 
                    },
                    { println("LLM server (PID: \$pid) is no longer running.") }
                )
            }
            pidFile.delete()
            println("🧹 Resources cleaned up.")
        } else {
            println("No active LLM server PID file found.")
        }
    }
}

tasks.register("startAnythingLlm") {
    group = "AI Assistant"
    description = "Starts the AnythingLLM UI."
    dependsOn("bootLlm")
    
    doLast {
        println("Booting AnythingLLM UI...")
        val uiPb = ProcessBuilder(anythingLlmAppImage.asFile.absolutePath, "--appimage-extract-and-run")
        uiPb.inheritIO()
        val uiProcess = uiPb.start()
        uiProcess.waitFor()
    }
}

// The standard 'run' task from the application plugin now smoothly waits for the LLM
tasks.named("run") {
    dependsOn("bootLlm")
}

tasks.test {
    useJUnitPlatform()
    dependsOn("bootLlm")
}
