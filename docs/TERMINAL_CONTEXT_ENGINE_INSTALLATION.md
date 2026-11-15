# Termylo Context Engine: integrated Windows runtime

TCE is an internal source-maintained part of **Termylo**. Users install and interact with Termylo only. TCE runs as an internal, locally approved helper process; it is not another desktop application, service, or separate product.

Architecture: ChatGPT -> Termylo MCP -> TCE adapter -> internal tce.exe -> local index and EmbeddingGemma 2.

The native engine is built from modified code at `tce-native/`, including the CLI, indexer, search service, model runtime, PDF, image, audio, and video readers. It is not the upstream executable renamed.

## Setup

- `context_setup` configures approved roots and, if necessary, installs the pinned Termylo-owned runtime to `%LOCALAPPDATA%\Termylo\ContextEngine\bin\tce.exe`.
- Or run `scripts/install-terminal-context.ps1 -WithModel` from Termylo.
- The installer checks the archive and each native file against SHA-256.
- Models: `%LOCALAPPDATA%\Termylo\ContextEngine\models`, about 865 MB, separately verified.
- Search and indexing remain disabled until `context_preflight`, `context_enable`, then `context_index` or `context_search`.
- `context_disable` turns off search. The native approval and project terminal windows are independent.

## Video retrieval

TCE uses one persistent search-service process. For video queries it requests a relevance threshold of 1.25 rather than starting an extra model process. These are candidate frame/segment matches, not complete understanding of an entire movie. Query latency after model warmup was about 0.02-0.06 seconds in the controlled tests. Large folder indexing still takes time.

## Native build

Windows x64 requires Swift 6.3.3, Visual Studio C++ Build Tools and Windows SDK, native model runtime, and vendor libraries. In `tce-native/`, run `scripts/fetch-vendor.sh` and `scripts/build-llama.sh` then `swift build -c release --product tce`. The repository release bundles its TCE executable, dependent DLLs, ffmpeg/ffprobe and licenses. No Swift compiler is needed by end users.

## Verification

- 112 native Swift tests passed, including video/image/indexing.
- 228 Python tests passed; 1 symlink test skipped for Windows privileges.
- Controlled known-answer retrieval: 13/13 correctly ranked top-1.
- Fresh indexing of three MP4s succeeded.
- False-positive rejection remains imperfect (10 of 12 negative queries returned matches). Results must be verified.

## Attribution

The TCE source is a maintained derivative of the MIT-licensed DigUp work by Abdur Rahim. Preserve the original copyright and MIT terms. Model assets have their own licenses. Attribution does not make DigUp a runtime dependency.
