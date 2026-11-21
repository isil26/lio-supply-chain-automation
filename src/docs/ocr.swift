import Foundation
import Vision

guard CommandLine.arguments.count == 2 else { exit(2) }

do {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    request.usesCPUOnly = true
    let available = try request.supportedRecognitionLanguages()
    request.recognitionLanguages = ["en-US", "pl-PL", "ko-KR", "zh-Hans", "de-DE"].filter { available.contains($0) }
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    let handler = VNImageRequestHandler(url: url)
    try handler.perform([request])
    let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    print(lines.joined(separator: "\n"))
} catch {
    FileHandle.standardError.write(Data("macOS Vision OCR unavailable\n".utf8))
    exit(1)
}
