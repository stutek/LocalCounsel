package com.compliance

import dev.langchain4j.model.chat.ChatLanguageModel
import dev.langchain4j.model.openai.OpenAiChatModel
import java.time.Duration
import kotlin.test.Test
import kotlin.test.assertTrue
import kotlin.test.assertNotNull

class LlmIntegrationTest {

    @Test
    fun testModelIdentification() {
        println("Initializing connection to local LLM sandbox...")
        
        // Connect to the local llama.cpp server provisioned by Gradle
        val model: ChatLanguageModel = OpenAiChatModel.builder()
            .baseUrl("http://127.0.0.1:8080/v1") // Pointing to local sandbox
            .apiKey("local")                     // Ignored by local server
            .modelName("gemma")
            .timeout(Duration.ofMinutes(2))
            .build()

        val prompt = "Hello! Please acknowledge this ping and confirm you are ready to review compliance documents."
        println("Prompting Model: $prompt")
        
        val response = model.generate(prompt)
        println("Model Response: $response")

        assertNotNull(response, "Response should not be null")
        assertTrue(response.isNotBlank(), "Response should not be empty")
    }
}
