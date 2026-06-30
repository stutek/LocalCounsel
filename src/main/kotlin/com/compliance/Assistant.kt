package com.compliance

import dev.langchain4j.model.chat.ChatLanguageModel
import dev.langchain4j.model.openai.OpenAiChatModel
import java.time.Duration

fun main() {
    println("==================================================")
    println("Compliance Assistant Initialized (Kotlin/LangChain4j)")
    println("==================================================")

    // Connect to the local llama.cpp server
    val model: ChatLanguageModel = OpenAiChatModel.builder()
        .baseUrl("http://127.0.0.1:8080/v1") // Pointing to local sandbox
        .apiKey("local")                     // Ignored by local server
        .modelName("gemma")
        .timeout(Duration.ofMinutes(5))
        .logRequests(true)
        .logResponses(true)
        .build()

    println("\nSystem ready to accept document parsing and compliance checks!")
    
    println("Sending test ping to local LLM...")
    val response = model.generate("Hello! Please introduce yourself, identify your core model architecture (e.g., Gemma, Llama), and confirm you are ready to review compliance documents.")
    println("\nModel Response: $response")
}
