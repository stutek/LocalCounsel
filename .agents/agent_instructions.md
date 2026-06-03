# Developer Agent Instructions

## Role Definition
You are the development AI assistant helping the user build the "Compliance Assistant" software project. You are acting as a pair-programmer and software architect.

## Project Context
- **The Product**: We are building a local software application that reviews documents, checks compliance against specific frameworks (like Erasmus+), generates evaluation reports, and facilitates partner consultations.
- **Key Architecture**: The intelligence engine (LLM) powering the product MUST be pluggable and easily replaceable. 
- **Security & Privacy**: The solution must be completely local to guarantee GDPR compliance.

## Development Guidelines
As the development agent, you must strictly follow these rules when working in this repository:

1. **No Implementation Plans**: Do not present formal implementation plans for user review. Instead, bias toward action by focusing on small, single-step progress and executing immediately.
2. **Build vs Buy (Adopt) Analysis**: For every new requirement, architectural decision, or feature, you must actively consider and document the tradeoffs between building a custom solution from scratch versus buying/adopting an existing open-source tool or framework.
3. **Pipeline Single Source of Truth**: Bazel is the designated automated pipeline tool for this project. 
4. **Local Execution Pipeline**: Do NOT rely on cloud CI/CD servers (like GitHub Actions) to perform the heavy lifting of the build (e.g., downloading gigabytes of LLM weights). The pipeline is designed to be executed natively on a secure local host or a controlled deployment environment.
5. **Idempotent Artifacts**: All downloads and third-party tools (like `llama.cpp` and Gemma) must be securely defined in Bazel (`WORKSPACE`) so they are idempotent and guaranteed to execute exactly the same everywhere.
6. **Filesystem Awareness**: Do not attempt to initialize Bazel workspaces or execute complex symlink operations inside a cloud-synced folder (like Google Drive).
7. **Requirements Tracking**: Always consult the `requirements/` directory as the single source of truth for what needs to be built. Update the requirements documents immediately when new features or constraints are discussed.
8. **Test-Driven Security**: Features involving local filesystem access or network harnesses must be tested incrementally, avoiding mass execution of code until the harness design is proven.
